"""Shared ReAct loop for main/planner/isolated workers, with durable yield boundaries."""
import asyncio
from dataclasses import replace
import json
from importlib.resources import files
from reactor_backend.models.types import ToolReply, encode
from reactor_backend.models.scope import model_scope, agent_scope
from reactor_backend.runtime.control import RunControl
from reactor_backend.runtime.local_tools import ToolScope,YieldInput
from reactor_backend.runtime.subagents import SubAgents
from reactor_backend.adapters.interactions import decoded, observation, client_payload

PLAN_INSTRUCTIONS='Plan mode is active: explore read-only locally; write only .reactor/plan.md. Do not search or modify other files. Use ExitPlanMode as the only call in its batch to ask approval. AskUserQuestion must also be alone. Child workers have independent tool scopes.'


class AttemptRecorder:
    def __init__(self,runtime,scope,step,messages,tools):
        self.runtime,self.scope,self.step,self.messages,self.tools=runtime,scope,step,messages,tools
        self.latest=None
    async def begin(self,model):
        self.latest=await self.runtime.ledger.start_llm(self.scope.control.run['id'],self.scope.control.next_llm(),self.step,model,self.messages,self.tools)
        return self.latest
    async def end(self,id,reply,error):
        await self.runtime.ledger.finish_llm(id,reply,error)
    async def notify(self,kind,payload):
        await self.scope.emit(kind,kind+':'+str(self.scope.control.llm_seq),{'resultMap':payload})


class ReAct:
    def __init__(self,ledger,model,tools,settings):
        self.ledger,self.model,self.tools,self.settings=ledger,model,tools,settings
        self.subagents=SubAgents(self)
        from reactor_backend.memory.service import Memory
        from reactor_backend.memory.working import Compactor
        from reactor_backend.skills.registry import Registry
        self.memory=Memory(ledger,model,settings.memory_settings)
        self.compactor=Compactor(model,settings.compaction_settings)
        self.skills=Registry(settings.skill_root)

    async def execute(self,query,publish,control=None):
        control=control or RunControl(query,publish)
        run=None;summary='';error=None;status=1;turn=[];yielded=None
        # Creation is shielded so stop during DB start can still finish the committed Run.
        creation=asyncio.create_task(self.ledger.start_run(query))
        try:run=await asyncio.shield(creation)
        except asyncio.CancelledError:
            run=await creation
            control.cancelled=True
        control.run=run
        try:
            control.checkpoint()
            context=await self.ledger.context(query.session_id)
            plan={'mode':'default','prePlanMode':'default'}
            if query.resume:
                saved=decoded(query.resume.get('resume_context_json'),{})
                plan.update(saved.get('planMode') or {})
                kind=query.resume['_kind']
                if kind=='approval':
                    decision=decoded(query.resume.get('decision_json'),{})
                    if decision.get('approved'):
                        plan.update(mode=plan.get('prePlanMode') or 'default',exitPendingApproval=False,hasExitedPlanMode=True,
                                    planContent=decision.get('editedPlanContent') or query.resume['plan_content'])
                        from reactor_backend.runtime.workspace import Workspace
                        await asyncio.to_thread(Workspace(self.settings.workspace_root,query.session_id).write,'.reactor/plan.md',plan['planContent'])
                    else:plan.update(mode='plan',exitPendingApproval=False)
                answer=encode(observation(kind,query.resume))
                call_id=query.resume['tool_call_id']
                matches=[m for m in context if m.get('role')=='tool' and m.get('tool_call_id')==call_id]
                if not matches:raise RuntimeError('Continuation tool observation missing; refusing side-effect replay')
                for m in matches:m['content']=answer
                await self.ledger.apply_continuation(query.resume,answer)
            elif query.force_plan_mode or query.agent_type==3 and not await self.ledger.prior_plan_turn(query.session_id,query.request_id):
                plan['mode']='plan'
            disabled=await self.ledger.capabilities(query.visitor_id,query.session_id) if hasattr(self.ledger,'capabilities') else []
            scope=ToolScope(self,control,query,plan=plan,disabled={kind:[r['ref_id'] for r in disabled if r['kind']==kind and not r['enabled']] for kind in ('skill','mcp')})
            prompt=files('reactor_backend.runtime').joinpath('planner_prompt.txt').read_text() if query.agent_type==3 else self.settings.system_prompt
            effective=replace(query,model=self.settings.planner_model or query.model) if query.agent_type==3 else query
            scope.query=effective
            scope.turn=turn
            # Only the model/tool loop is cancelled; supervisor owns final persistence and child draining.
            control.root_task=asyncio.create_task(self.loop(scope,prompt,context,self.settings.planner_max_steps if query.agent_type==3 else self.settings.max_steps,control.injections))
            try:
                summary,_,turn=await control.root_task
            except YieldInput as signal:
                # loop already persisted the waiting tool observation; finish Run before exposing card.
                yielded=signal.record;turn=scope.turn;status=5
            except BaseException:
                turn=scope.turn
                raise
        except asyncio.CancelledError:
            status,error=4,'Run stopped'
        except Exception as exc:
            status,error=2,str(exc)
        control.root_closed=True
        if status not in (1,5):turn=self._complete_pairs(turn)
        if control.cancelled:
            # Any yield committed while stop was awaiting DB cancellation must also be cancelled.
            if hasattr(self.ledger,'stop_interactions'):
                await self.ledger.stop_interactions(query.visitor_id,query.request_id,query.session_id)
            status,error=4,'Run stopped'
        kwargs={}
        if hasattr(self.ledger,'replace_projection') and 'scope' in locals() and getattr(scope,'compactions',None):
            kwargs=dict(projection=self._complete_pairs(scope.messages[1:]) if any(e['strategy']!='abort-unchanged' for e in scope.compactions) else None,compactions=scope.compactions)
        durable=await self.ledger.finish_run(run,status,summary,error,turn,**kwargs)
        if durable is not None:status=durable
        if query.resume:
            await self.ledger.settle_interaction(query.resume['_kind'],query.request_id,'ANSWERED' if status in (1,5) else 'FAILED')
        if yielded and status==5:
            payload=client_payload(yielded['_kind'],yielded)
            await control.emit(payload['messageType'],yielded['tool_call_id']+':waiting',{'resultMap':payload},finished=not bool(control.children))
        else:
            await control.emit('result',query.request_id+':summary',{'result':summary,'taskSummary':summary,'finish':not bool(control.children)},
                               finished=not bool(control.children),status='success' if status==1 else 'failed',errorMsg=error)
        had_children=bool(control.children)
        await self.subagents.settle_cancelled(control)
        if hasattr(self.ledger,'refresh_run_counts'):await self.ledger.refresh_run_counts(run['id'])
        if had_children:
            await control.emit('stream_settle',query.request_id+':settle',{'resultMap':{'finish':True,'status':'stopped' if control.cancelled else 'idle'},'finish':True},finished=True)
        if status==1 and 'scope' in locals():self.memory.success(scope,scope.messages,scope.visible())

    async def loop(self,scope,prompt,context,max_steps,inbox):
        q=scope.query;control=scope.control
        turn=getattr(scope,'turn',[]);scope.turn=turn
        if not q.resume:
            content=q.query or ''
            if q.session_files:content+='\nAttached session files:\n'+encode(q.session_files)
            turn.append({'role':'user','content':content})
        try:
            await scope.initialize()
            prompt+='\n'+await self.memory.prompt(scope)
        except BaseException:
            await scope.close()
            raise
        messages=[{'role':'system','content':prompt}]+context+turn.copy()
        scope.messages=messages;scope.compactions=[]
        count=0
        token=agent_scope.set(scope.child or {'agent_name':'plan-solve' if q.agent_type==3 else 'react'})
        try:
            for step in range(1,max_steps+1):
                control.checkpoint()
                while inbox:
                    injected=inbox.popleft() if hasattr(inbox,'popleft') else inbox.pop(0)
                    injected=injected if isinstance(injected,dict) else {'text':str(injected)}
                    m={'role':'user','content':'[User guidance] '+injected['text']}
                    messages.append(m);turn.append(m)
                    if not injected.get('notified'):await scope.emit('user_inject','inject:'+str(control.llm_seq)+':'+str(len(turn)),{'resultMap':{'text':injected['text'],'message':injected['text']}})
                messages[0]={'role':'system','content':prompt+('\n'+PLAN_INSTRUCTIONS if scope.plan.get('mode')=='plan' else '')+'\n'+scope.mcp.prompt()}
                schemas=scope.visible()
                window=self.settings.context_window
                if hasattr(self.model,'catalog'):window=(await self.model.catalog.resolve(q.model)).context_window
                messages,compact=await self.compactor.compact(messages,schemas,q,window,before_compact=lambda m,t:self.memory.flush(scope,m,t),memory_scope='sub:'+scope.child['subAgentId'] if scope.child else 'main')
                scope.messages=messages
                if compact:
                    scope.compactions.append(compact)
                recording=AttemptRecorder(self,scope,step,messages,schemas)
                recording_token=model_scope.set(recording)
                try:
                    if hasattr(self.model,'_binding'):
                        reply=await self.model.complete(messages,schemas,q)
                    else:
                        llm=await recording.begin(q.model)
                        try:reply=await self.model.complete(messages,schemas,q)
                        except BaseException as exc:
                            await recording.end(llm,None,'Cancelled' if isinstance(exc,asyncio.CancelledError) else str(exc));raise
                        await recording.end(llm,reply,None)
                finally:model_scope.reset(recording_token)
                control.checkpoint()
                if scope.child and asyncio.current_task().cancelling():raise asyncio.CancelledError('Child stopped')
                if reply.reasoning:await scope.emit('llm_reasoning',f'{q.request_id}:{step}:reasoning',{'reasoningContent':reply.reasoning})
                message=reply.message();messages.append(message);turn.append(message)
                if not reply.calls:
                    if not reply.content.strip():raise RuntimeError('Empty final model response')
                    if scope.child:await scope.emit('task_summary',q.request_id+':summary',{'taskSummary':reply.content,'resultMap':{'result':reply.content}})
                    return reply.content,count,turn
                if reply.content:await scope.emit('tool_thought',f'{q.request_id}:{step}',{'toolThought':reply.content})
                registered=[]
                sole_violation=len(reply.calls)>1 and any(c.name in ('AskUserQuestion','ExitPlanMode') for c in reply.calls)
                for index,call in enumerate(reply.calls):
                    parse_error=None
                    try:
                        args=json.loads(call.arguments)
                        if not isinstance(args,dict):raise ValueError('Tool arguments must be a JSON object')
                    except (ValueError,TypeError) as exc:args,parse_error={'rawArguments':call.arguments},str(exc)
                    tool_id=await self.ledger.start_tool(control.run['id'],recording.latest,call,index,step,args)
                    registered.append((call,args,parse_error,tool_id,index))
                    await scope.emit('tool_call',call.id,{'resultMap':dict(toolCallId=call.id,toolName=call.name,toolParam=args,status='running',dispatchIndex=index)})
                count+=len(registered)
                async def execute_one(item):
                    call,args,parse_error,tool_id,index=item
                    try:
                        if sole_violation:result=ToolReply(failed=True,error='AskUserQuestion/ExitPlanMode must be the only tool call in this batch; no batch tools were executed')
                        elif parse_error:result=ToolReply(failed=True,error='Invalid tool arguments: '+parse_error)
                        else:result=await scope.execute(call.name,args,call,tool_id)
                    except YieldInput as signal:
                        snap=dict(entryAgent='plan_solve' if q.agent_type==3 else 'react',agentType=q.agent_type,model=q.model,thinking=q.thinking,thinkingEffort=q.thinking_effort,planMode=scope.plan)
                        record=await self.ledger.create_interaction(signal.kind,q,control.run,call,tool_id,signal.content,snap,signal.path)
                        record['_kind']=signal.kind
                        waiting=encode(observation(signal.kind,record,True))
                        await self.ledger.waiting_tool(tool_id,waiting)
                        turn.append({'role':'tool','tool_call_id':call.id,'content':waiting})
                        messages.append({'role':'tool','tool_call_id':call.id,'content':waiting})
                        signal.record=record
                        raise
                    refs=[]
                    if result.files:
                        try:refs=await self.ledger.register_artifacts(control.run,tool_id,call,result.files)
                        except Exception as exc:result=ToolReply(failed=True,error='Artifact registration failed: '+type(exc).__name__,data={'tool':call.name,'registration_failed':True})
                    obs=result.observation()
                    await self.ledger.finish_tool(tool_id,result,obs)
                    self.subagents.receipt_saved(q.session_id,result)
                    if call.name in ('code_interpreter','data_analysis','multimodalagent_tool','deep_search'):
                        from reactor_backend.projection.tool_history import project
                        artifact_rows=[{'file_name':f['fileName'],'download_url':f.get('downloadUrl') or f.get('ossUrl'),'preview_url':f.get('previewUrl') or f.get('domainUrl'),'file_size':f.get('fileSize')} for f in result.files]
                        for kind,payload,_ in project({'tool_name':call.name,'tool_call_id':call.id,'structured_output':result.structured_output,'llm_oberserve':obs},args,artifact_rows) or []:
                            await scope.emit(kind,call.id+':rich',{'resultMap':{**payload,'toolCallId':call.id}},refs=refs)
                    if not result.failed and call.name in ('emit_ui_tree','emit_ui_patch'):
                        from reactor_backend.projection.genui import recover
                        kind,payload=recover({'tool_name':call.name,'tool_call_id':call.id,'structured_output':result.structured_output},args)
                        await scope.emit(kind,call.id+':'+kind,{'resultMap':payload})
                    if not result.failed and call.name=='canvas_publish' and result.structured_output.get('open_in_panel'):
                        from reactor_backend.projection.tool_history import project
                        artifact_rows=[{'file_name':f['fileName'],'download_url':f.get('downloadUrl'),'preview_url':f.get('previewUrl'),'file_size':f.get('fileSize')} for f in result.files]
                        for kind,payload,_ in project({'tool_name':call.name,'tool_call_id':call.id,'structured_output':result.structured_output,'llm_oberserve':obs},args,artifact_rows):
                            await scope.emit(kind,call.id+':'+kind,{'resultMap':{**payload,'toolCallId':call.id,'toolName':call.name}},refs=refs)
                    if refs:await scope.emit('file',call.id+':file',{'resultMap':dict(command='生成图片' if call.name=='image_generation_tool' else '文档处理',fileInfo=result.files,toolCallId=call.id,toolName=call.name)},refs=refs)
                    await scope.emit('tool_result',call.id+':tool_result',{'toolResult':dict(toolName=call.name,toolParam=args,toolResult=obs,toolCallId=call.id)},refs=refs)
                    return {'role':'tool','tool_call_id':call.id,'content':obs}
                results=await asyncio.gather(*(execute_one(i) for i in registered),return_exceptions=True)
                failures=[o for o in results if isinstance(o,BaseException)]
                if failures:raise failures[0]
                messages.extend(results);turn.extend(results)
            raise RuntimeError('Agent exceeded max_steps without a final answer')
        finally:
            agent_scope.reset(token)
            await scope.close()

    @staticmethod
    def _complete_pairs(messages):
        result=[]
        for index,m in enumerate(messages):
            if m.get('tool_calls'):
                ids={c['id'] for c in m['tool_calls']}
                subsequent={x.get('tool_call_id') for x in messages[index+1:] if x['role']=='tool'}
                if not ids.issubset(subsequent):break
            result.append(m)
        return result
