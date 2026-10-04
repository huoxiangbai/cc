"""Real child execution with independent memory/tools, bounded admission and durable outputs."""
import asyncio
from dataclasses import replace
from time import time,monotonic
from uuid import uuid4
from reactor_backend.models.types import ToolReply
from reactor_backend.runtime.local_tools import ToolScope


def output_fields(task,retrieval='success'):
    data=dict(retrieval_status=retrieval,task_id=task['task_id'],task_type=task['type'],status=task['status'],description=task.get('description'))
    for column,key in (('agent_id','agentId'),('agent_type','agentType'),('error_msg','error'),('total_tool_use_count','totalToolUseCount'),('total_duration_ms','totalDurationMs'),('ended_at_ms','endedAtMs')):
        if task.get(column) is not None:data[key]=task[column]
    if task.get('output'):data.update(output=task['output'],result=task['output'])
    data['message']='任务仍在运行，等待超时。可再次 TaskOutput 或 TaskStop。' if retrieval=='timeout' else '任务仍在运行（未阻塞等待）。' if retrieval=='not_ready' else {'completed':'任务已完成。','stopped':'任务已停止。','failed':'任务失败：'+str(task.get('error_msg') or '')}.get(task['status'],'ok')
    return data


class SubAgents:
    def __init__(self,runtime):
        self.runtime=runtime
        self.gate=asyncio.Semaphore(runtime.settings.max_subagents)
        self.running={}
        self.agents={}
        self.reserved=set()

    async def dispatch(self,parent,args,call,tool_id):
        q=parent.query;control=parent.control
        desc=str(args.get('description') or '').strip();prompt=str(args.get('prompt') or '').strip()
        if not desc or not prompt:raise ValueError('description 与 prompt 必填')
        resume=str(args.get('resume_agent_id') or '').strip() or None
        name=str(args.get('subagent_type') or '').strip() or None
        agent_id=resume or uuid4().hex[:16]
        key=(q.session_id,agent_id)
        if key in self.reserved or key in self.agents:
            raise ValueError('子 Agent 仍在运行；请使用 SendMessage')
        self.reserved.add(key)
        try:
            prior=None
            if resume:
                prior=await self.runtime.ledger.background_get(q,agent_id=resume)
                if not prior:raise ValueError('Unknown resume_agent_id in this session')
                if prior['status']=='running':raise ValueError('子 Agent 仍在运行；请使用 SendMessage')
                if name and name!=prior['agent_type']:raise ValueError('resume agent type mismatch')
                name=prior['agent_type']
            definition=await self.runtime.ledger.child_definition(name)
            control.checkpoint()
            task_id=uuid4().hex
            task=dict(session_id=q.session_id,task_id=task_id,type='local_agent',status='running',description=desc,
                      agent_id=agent_id,agent_type=definition['agent_key'],prompt=prompt,started_at_ms=int(time()*1000))
            await self.runtime.ledger.background_create(q,task)
            if control.cancelled:
                await self.runtime.ledger.background_settle(q.session_id,task_id,'stopped',error='cancelled before bind')
            control.checkpoint()
            receipt=asyncio.Event()
            background=args.get('run_in_background') is True
            tags=dict(agent_name=('subagent:'+definition['agent_key'])[:32],parentToolUseId=call.id,subAgentId=agent_id,
                      subAgentType=definition['agent_key'],subAgentDescription=desc[:256])
            mailbox=control.mailboxes.setdefault(agent_id,[])
            child_query=replace(q,request_id='sub:'+agent_id+':'+uuid4().hex[:8],query=prompt,agent_type=5,force_plan_mode=False,resume=None)
            scope=ToolScope(self.runtime,control,child_query,child=tags,definition=definition,disabled=parent.disabled)
            started=asyncio.Event()
            async def execute():
                started.set()
                start=monotonic();result=None;error=None;count=0;status='failed'
                try:
                    # Waiters consume no parent tool semaphore; child Agent is globally forbidden, so no nested gate deadlock.
                    async with asyncio.timeout(self.runtime.settings.subagent_wait_seconds):
                        await self.gate.acquire()
                    try:
                        control.checkpoint()
                        context=await self.runtime.ledger.context(q.session_id,'sub:'+agent_id) if resume else []
                        result,count,messages=await self.runtime.loop(scope,definition['system_prompt'],context,definition.get('max_steps') or self.runtime.settings.max_steps,mailbox)
                        control.checkpoint()
                        child_run={**control.run,'request_id':child_query.request_id,'entry_agent':'react'}
                        kwargs=dict(projection=scope.messages[1:] if any(e['strategy']!='abort-unchanged' for e in scope.compactions) else None,compactions=scope.compactions) if hasattr(self.runtime.ledger,'replace_projection') and scope.compactions else {}
                        await self.runtime.ledger.save_child_context(child_run,messages,'sub:'+agent_id,**kwargs)
                        status='completed'
                    finally:self.gate.release()
                except asyncio.CancelledError:
                    status,error='stopped','cancelled'
                except Exception as exc:
                    error=str(exc)
                finally:
                    if getattr(scope,'turn',None) and status!='completed':
                        child_run={**control.run,'request_id':child_query.request_id,'entry_agent':'react'}
                        await self.runtime.ledger.save_child_context(child_run,self.runtime._complete_pairs(scope.turn),'sub:'+agent_id)
                    await self.runtime.ledger.background_settle(q.session_id,task_id,status,result,error,count,int((monotonic()-start)*1000))
                    persisted=await self.runtime.ledger.background_get(q,task_id=task_id)
                    status=persisted['status'];result=persisted.get('output');error=persisted.get('error_msg')
                    fields=output_fields(persisted)
                    await scope.emit('subagent_progress',agent_id+':settled',{'resultMap':fields})
                    if background:
                        # The receipt must be durable before final settlement, including very fast children.
                        await receipt.wait()
                        final=ToolReply(data=dict(tool='Agent',ok=persisted['status']=='completed',**fields,run_in_background=True))
                        await self.runtime.ledger.settle_agent_tool(tool_id,final.observation())
                        await parent.emit('tool_result',call.id+':background_result',{'toolResult':dict(toolName='Agent',toolParam=args,toolCallId=call.id,toolResult=final.observation())})
                    self.running.pop((q.session_id,task_id),None)
                    self.agents.pop(key,None)
                    control.mailboxes.pop(agent_id,None)
                return ToolReply(data=dict(tool='Agent',ok=status=='completed',agentId=agent_id,agentType=definition['agent_key'],
                    description=desc,prompt=prompt,status=status,content=result or '',result=result or '',totalToolUseCount=count,totalDurationMs=int((monotonic()-start)*1000),
                    **({'resumed':True,'resume_agent_id':agent_id} if resume else {})),failed=status!='completed',error=error)
            future=asyncio.create_task(execute(),name='sub:'+agent_id)
            self.running[(q.session_id,task_id)]=(future,control,receipt)
            self.agents[key]=task_id
            control.children.add(future)
            future.add_done_callback(control.children.discard)
            async def never_started():
                try:
                    await self.runtime.ledger.background_settle(q.session_id,task_id,'stopped',error='cancelled before bind')
                    persisted=await self.runtime.ledger.background_get(q,task_id=task_id)
                    fields=output_fields(persisted)
                    await scope.emit('subagent_progress',agent_id+':settled',{'resultMap':fields})
                    if background:
                        await receipt.wait()
                        final=ToolReply(data=dict(tool='Agent',ok=False,**fields,run_in_background=True))
                        await self.runtime.ledger.settle_agent_tool(tool_id,final.observation())
                        await parent.emit('tool_result',call.id+':background_result',{'toolResult':dict(toolName='Agent',toolParam=args,toolCallId=call.id,toolResult=final.observation())})
                finally:
                    self.running.pop((q.session_id,task_id),None)
                    self.agents.pop(key,None)
                    control.mailboxes.pop(agent_id,None)
            def completed(task):
                if task.cancelled() and not started.is_set():
                    cleanup=asyncio.create_task(never_started(),name='subagent-cancel:'+agent_id)
                    control.children.add(cleanup)
                    cleanup.add_done_callback(control.children.discard)
            future.add_done_callback(completed)
            if background:
                reply=ToolReply(data=dict(tool='Agent',ok=True,status='running',task_id=task_id,agentId=agent_id,task_type='local_agent',description=desc,
                    agentType=definition['agent_key'],run_in_background=True,message='后台子 Agent 已启动。用 TaskOutput 取结果、SendMessage 指导、TaskStop 取消。'))
                return reply
            receipt.set()
            return await future
        finally:self.reserved.discard(key)

    def receipt_saved(self,session,reply):
        if isinstance(reply.data,dict) and reply.data.get('task_id'):
            running=self.running.get((session,reply.data['task_id']))
            if running:running[2].set()

    async def task_tool(self,scope,name,a):
        q=scope.query
        task_id=str(a.get('task_id') or a.get('shell_id') or '').strip()
        if name=='SendMessage':
            to=str(a.get('to') or '').strip();message=str(a.get('message') or '').strip()
            if not to or not message:raise ValueError('to 与 message 必填')
            task=await self.runtime.ledger.background_get(q,task_id=to)
            if not task:task=await self.runtime.ledger.background_get(q,agent_id=to)
            running=self.running.get((q.session_id,task['task_id'])) if task else None
            if not running or task['status']!='running' or running[0].done():
                return ToolReply(data=dict(tool=name,ok=False,to=to,message='目标子 Agent 未在运行；请使用 Agent(resume_agent_id=…)'))
            running[1].mailboxes.setdefault(task['agent_id'],[]).append(dict(text=message[:8000],summary=a.get('summary')))
            return ToolReply(data=dict(tool=name,ok=True,to=to,agentId=task['agent_id'],task_id=task['task_id'],message='指导已入队'))
        if not task_id:raise ValueError('task_id 必填')
        task=await self.runtime.ledger.background_get(q,task_id=task_id)
        if not task:raise ValueError('Task not found: '+task_id)
        running=self.running.get((q.session_id,task_id))
        if name=='TaskStop':
            if task['status']!='running':return ToolReply(failed=True,error='Task not running: '+task_id)
            changed=await self.runtime.ledger.background_settle(q.session_id,task_id,'stopped',error='cancelled')
            if running:
                running[2].set();running[0].cancel()
            if not changed:return ToolReply(failed=True,error='Task not running: '+task_id)
            return ToolReply(data=dict(tool=name,ok=True,task_id=task_id,task_type=task['type'],status='stopped',agentId=task['agent_id'],message='已发送取消令牌'))
        retrieval='success'
        if task['status']=='running':
            block=a.get('block',True)
            block=block is True or str(block).lower() in ('true','1','yes')
            if block and running:
                try:timeout=max(0,min(int(a.get('timeout',30000)),600000))/1000
                except (ValueError,TypeError):timeout=30
                try:await asyncio.wait_for(asyncio.shield(running[0]),timeout)
                except TimeoutError:retrieval='timeout'
                except asyncio.CancelledError:
                    scope.control.checkpoint()
                    if not running[0].cancelled():raise
                task=await self.runtime.ledger.background_get(q,task_id=task_id)
            else:retrieval='not_ready'
        return ToolReply(data=dict(tool=name,ok=True,**output_fields(task,retrieval)))

    async def settle_cancelled(self,control):
        # Handles a task cancelled before its first instruction, plus release of receipt waiters.
        for (session,task_id),(future,owner,receipt) in tuple(self.running.items()):
            if owner is not control:continue
            receipt.set()
            if control.cancelled:
                await self.runtime.ledger.background_settle(session,task_id,'stopped',error='cancelled')
                future.cancel()
        await control.drain()
        for key,(future,owner,_) in tuple(self.running.items()):
            if owner is control and future.done():
                self.running.pop(key,None)
                for agent,task_id in tuple(self.agents.items()):
                    if agent[0]==key[0] and task_id==key[1]:self.agents.pop(agent,None)
