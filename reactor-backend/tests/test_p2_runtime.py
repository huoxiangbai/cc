"""Deterministic scheduler tests. Fixtures are confined to tests; production adapters are unchanged."""
import asyncio
from collections import deque
from dataclasses import replace
import json
from pathlib import Path
from uuid import uuid4
import pytest
from reactor_backend.runtime.react import ReAct
from reactor_backend.runtime.local_tools import ToolScope
from reactor_backend.runtime.control import RunControl
from reactor_backend.runtime.workspace import Workspace
from reactor_backend.application.runs import Runs,RunStream
from reactor_backend.models.types import ToolCall,ModelReply,ToolReply
from reactor_backend.bootstrap.config import Settings
from test_contracts import Q,MemoryLedger,FixedTools


def call(name,args=None,id=None):return ModelReply(calls=[ToolCall(id or uuid4().hex,name,json.dumps(args or {}))])


class Ledger(MemoryLedger):
    def __init__(self):
        super().__init__();self.runs=[];self.background={};self.memories={};self.settled=[];self.waiting=[];self.cards=[]
    async def start_run(self,q):
        r=dict(id=len(self.runs)+1,request_id=q.request_id,session_id=q.session_id,status=0,visitor_id=q.visitor_id,entry_agent='plan_solve' if q.agent_type==3 else 'react')
        self.runs.append(r);return r
    async def finish_run(self,r,status,summary,error,turn):
        if r['status']==0:r['status']=status;self.finished.append((r,status,summary,error,turn))
        self.memories.setdefault((r['session_id'],'main'),[]).extend(turn)
        return r['status']
    async def context(self,s,scope='main'):return list(self.memories.get((s,scope),[]))
    async def save_child_context(self,r,m,scope):self.memories.setdefault((r['session_id'],scope),[]).extend(m)
    async def prior_plan_turn(self,s,r):return False
    async def capabilities(self,*args):return []
    async def child_definition(self,name):return dict(agent_key=name or 'general-purpose',system_prompt='child system',allowed_tools_json=['*'],disallowed_tools_json=[],max_steps=10)
    async def background_create(self,q,t):self.background[(q.session_id,t['task_id'])]=dict(t)
    async def background_get(self,q,task_id=None,agent_id=None):
        return next((t for (session,key),t in reversed(list(self.background.items())) if session==q.session_id and (key==task_id if task_id else t['agent_id']==agent_id)),None)
    async def background_settle(self,s,t,status,output=None,error=None,tools=0,duration=0):
        row=self.background[(s,t)]
        if row['status']!='running':return 0
        row.update(status=status,output=output,error_msg=error,total_tool_use_count=tools,total_duration_ms=duration);return 1
    async def settle_agent_tool(self,*a):self.settled.append(a)
    async def waiting_tool(self,*a):self.waiting.append(a)
    async def create_interaction(self,kind,q,r,c,tid,content,ctx,path=None):
        row=dict(session_id=q.session_id,source_request_id=q.request_id,source_run_id=r['id'],tool_call_id=c.id,tool_invocation_id=tid,status='PENDING',resume_context_json=ctx,visitor_id=q.visitor_id)
        if kind=='question':row.update(question_id='q',questions_json=content)
        else:row.update(approval_id='a',plan_content=content,plan_file_path=path)
        self.cards.append(row);return row
    async def stop_interactions(self,*a):return 0,[]


async def wait_for(predicate):
    async with asyncio.timeout(2):
        while not predicate():await asyncio.sleep(0)


@pytest.mark.parametrize('point',['before-bind','model','tool'])
async def test_stop_admission_to_bound_execution(point,tmp_path):
    entered=asyncio.Event();release=asyncio.Event();effects=[]
    class Model:
        async def complete(self,m,t,q):
            if point=='model':entered.set();await release.wait()
            return call('text_processor')
    class Tools(FixedTools):
        async def execute(self,*a):entered.set();await release.wait();effects.append('late');return ToolReply(data='done')
    ledger=Ledger();runs=Runs(ReAct(ledger,Model(),Tools(),Settings('unused','unused',tmp_path)))
    stream=runs.start(Q)
    if point!='before-bind':await entered.wait()
    assert runs.stop(Q.request_id)==(True,True)
    assert runs.stop(Q.request_id)==(True,False)
    release.set();await runs.drain()
    assert ledger.runs[0]['status']==4 and not effects and not runs.visitors
    assert stream.closed and stream.buffer[-1]['finished']


async def test_same_visitor_cross_session_and_different_visitor_concurrent(tmp_path):
    entered=[];release=asyncio.Event()
    class Model:
        async def complete(self,m,t,q):entered.append(q.request_id);await release.wait();return ModelReply(content='done')
    ledger=Ledger();runs=Runs(ReAct(ledger,Model(),FixedTools(),Settings('unused','unused',tmp_path)))
    a=runs.start(Q)
    with pytest.raises(ValueError,match='访客'):runs.start(replace(Q,request_id='b',session_id='s-b'))
    b=runs.start(replace(Q,request_id='b',session_id='s-b',visitor_id='other'))
    await wait_for(lambda:len(entered)==2)
    release.set();await runs.drain()
    assert a.closed and b.closed and len(ledger.finished)==2


async def test_claim_to_admission_stop_is_retained_before_bind(tmp_path):
    effects=[]
    class Model:
        async def complete(self,*a):effects.append('model');return ModelReply(content='unexpected')
    ledger=Ledger();runs=Runs(ReAct(ledger,Model(),FixedTools(),Settings('unused','unused',tmp_path)))
    assert runs.stop(Q.request_id,pending=True)==(True,True)
    assert runs.stop(Q.request_id,pending=True)==(True,False)
    runs.start(Q);await runs.drain()
    assert not effects and ledger.runs[0]['status']==4 and not runs.pending_stops


async def test_old_observer_abort_does_not_detach_new_and_128_cursor():
    stream=RunStream(Q)
    for i in range(1,145):await stream.publish({'eventSeq':i,'packageType':'result'})
    old=stream.attach(140);new=stream.attach(142)
    stream.detach(old)
    assert new in stream.observers and old not in stream.observers
    assert [new.get_nowait()['eventSeq'],new.get_nowait()['eventSeq']]==[143,144]
    assert len(stream.buffer)==128
    await stream.publish({'eventSeq':0,'packageType':'heartbeat'})
    assert len(stream.buffer)==128 and stream.buffer[-1]['eventSeq']==144


@pytest.mark.parametrize('yield_name',['AskUserQuestion','ExitPlanMode'])
async def test_hitl_sole_call_no_other_batch_side_effect(yield_name,tmp_path):
    effects=[]
    class Model:
        def __init__(self):self.i=0
        async def complete(self,*a):
            self.i+=1
            return ModelReply(calls=[ToolCall('yield',yield_name,'{}'),ToolCall('mutation','text_processor','{}')]) if self.i==1 else ModelReply(content='corrected')
    class Tools(FixedTools):
        async def execute(self,*a):effects.append(a);return ToolReply(data='bad')
    ledger=Ledger();runtime=ReAct(ledger,Model(),Tools(),Settings('unused','unused',tmp_path))
    events=[]
    async def publish(e):events.append(e)
    await runtime.execute(Q,publish)
    assert not ledger.cards and not effects and ledger.runs[0]['status']==1
    observations=ledger.finished[0][-1]
    assert sum('only tool' in m.get('content','') for m in observations if m.get('role')=='tool')==2


async def test_planner_first_turn_waiting_and_prompt_scope(tmp_path):
    snapshots=[]
    class Model:
        async def complete(self,m,t,q):
            snapshots.append((m,t,q));return call('ExitPlanMode',{'plan':'研究计划'})
    ledger=Ledger();events=[]
    async def publish(e):events.append(e)
    await ReAct(ledger,Model(),FixedTools(),Settings('unused','unused',tmp_path,planner_model='planner')).execute(replace(Q,agent_type=3),publish)
    assert ledger.runs[0]['status']==5 and snapshots[0][2].model=='planner'
    assert 'PLAN_SOLVE_ORCHESTRATION_V6' in snapshots[0][0][0]['content'] and 'Plan mode is active' in snapshots[0][0][0]['content']
    assert (tmp_path/Q.session_id/'.reactor/plan.md').read_text()=='研究计划'
    assert events[-1]['resultMap']['agentType']==3 and events[-1]['resultMap']['eventData']['resultMap']['messageType']=='plan_approval'
    assert json.loads(ledger.waiting[0][1])['status']=='waiting_user_input'


async def test_background_root_returns_followable_until_drain_and_settle(tmp_path):
    child_started=asyncio.Event();release=asyncio.Event()
    class Model:
        async def complete(self,m,t,q):
            if q.request_id.startswith('sub:'):
                child_started.set();await release.wait();return ModelReply(content='child actual result')
            return call('Agent',dict(description='worker',prompt='child task',run_in_background=True)) if not any(x['role']=='tool' for x in m) else ModelReply(content='root returned')
    ledger=Ledger();runs=Runs(ReAct(ledger,Model(),FixedTools(),Settings('unused','unused',tmp_path)))
    stream=runs.start(Q);await child_started.wait()
    await wait_for(lambda:stream.control.root_closed)
    await wait_for(lambda:any(f.get('resultMap',{}).get('eventData',{}).get('resultMap',{}).get('messageType')=='result' for f in stream.buffer))
    root=[f for f in stream.buffer if f['resultMap']['eventData']['resultMap']['messageType']=='result'][-1]
    assert not root['finished'] and not root['resultMap']['eventData']['resultMap']['finish']
    assert Q.request_id in runs.active and Q.visitor_id in runs.visitors
    stream.attach(root['eventSeq'])
    release.set();await runs.drain()
    assert stream.buffer[-1]['resultMap']['eventData']['resultMap']['messageType']=='stream_settle' and stream.buffer[-1]['finished']
    assert ledger.settled and all(t['status']=='completed' for t in ledger.background.values())
    assert (Q.session_id,'main') in ledger.memories and len(ledger.memories)==2
    child_memory=next(v for (s,scope),v in ledger.memories.items() if scope!='main')
    assert child_memory[0]['content']=='child task' and not any(m.get('content')=='hello' for m in child_memory)


async def test_task_output_timeout_no_cancel_mailbox_fifo_and_task_stop(tmp_path):
    entered=asyncio.Event();release=asyncio.Event();messages=[]
    class Model:
        async def complete(self,m,t,q):
            if q.request_id.startswith('sub:'):
                messages.append(list(m))
                if not any(x['role']=='tool' for x in m):entered.set();await release.wait();return call('text_processor')
                return ModelReply(content='child done')
            return ModelReply(content='unused')
    ledger=Ledger();runtime=ReAct(ledger,Model(),FixedTools(),Settings('unused','unused',tmp_path))
    c=RunControl(Q,lambda e:asyncio.sleep(0));c.run=await ledger.start_run(Q)
    scope=ToolScope(runtime,c,Q)
    receipt=await runtime.subagents.dispatch(scope,dict(description='bg',prompt='independent',run_in_background=True),ToolCall('parent','Agent','{}'),1)
    runtime.subagents.receipt_saved(Q.session_id,receipt);await entered.wait()
    output=await runtime.subagents.task_tool(scope,'TaskOutput',dict(task_id=receipt.data['task_id'],timeout=0))
    assert output.data['retrieval_status']=='timeout' and not next(iter(runtime.subagents.running.values()))[0].cancelled()
    for text in ('first','second'):
        reply=await runtime.subagents.task_tool(scope,'SendMessage',dict(to=receipt.data['agentId'],message=text))
        assert reply.data['ok']
    release.set();await c.drain()
    assert [m['content'] for m in messages[-1] if m['role']=='user']==['independent','[User guidance] first','[User guidance] second']
    reply=await runtime.subagents.task_tool(scope,'SendMessage',dict(to=receipt.data['agentId'],message='late'))
    assert reply.data['ok'] is False
    assert (await runtime.subagents.task_tool(scope,'TaskOutput',dict(task_id=receipt.data['task_id']))).data['result']=='child done'


async def test_task_stop_and_late_result_do_not_override_stopped(tmp_path):
    entered=asyncio.Event();release=asyncio.Event()
    class Model:
        async def complete(self,*a):
            entered.set()
            try:await release.wait()
            except asyncio.CancelledError:await release.wait()  # an uncooperative upstream completion
            return ModelReply(content='late success')
    ledger=Ledger();runtime=ReAct(ledger,Model(),FixedTools(),Settings('unused','unused',tmp_path))
    c=RunControl(Q,lambda e:asyncio.sleep(0));c.run=await ledger.start_run(Q);scope=ToolScope(runtime,c,Q)
    receipt=await runtime.subagents.dispatch(scope,dict(description='bg',prompt='task',run_in_background=True),ToolCall('parent','Agent','{}'),1)
    runtime.subagents.receipt_saved(Q.session_id,receipt);await entered.wait()
    stopped=await runtime.subagents.task_tool(scope,'TaskStop',dict(shell_id=receipt.data['task_id']))
    release.set();await c.drain()
    assert stopped.data['status']=='stopped' and ledger.background[(Q.session_id,receipt.data['task_id'])]['status']=='stopped'
    assert (await runtime.subagents.task_tool(scope,'TaskOutput',dict(task_id=receipt.data['task_id']))).data['status']=='stopped'
    assert all(not any(m.get('content')=='late success' for m in messages) for messages in ledger.memories.values())


async def test_fast_child_receipt_then_final_and_resume_isolation(tmp_path):
    captured=[]
    class Model:
        async def complete(self,m,t,q):captured.append(list(m));return ModelReply(content='child completed')
    ledger=Ledger();runtime=ReAct(ledger,Model(),FixedTools(),Settings('unused','unused',tmp_path))
    c=RunControl(Q,lambda e:asyncio.sleep(0));c.run=await ledger.start_run(Q);scope=ToolScope(runtime,c,Q)
    r=await runtime.subagents.dispatch(scope,dict(description='fast',prompt='first child',run_in_background=True),ToolCall('parent','Agent','{}'),1)
    await wait_for(lambda:ledger.background[(Q.session_id,r.data['task_id'])]['status']=='completed')
    assert not ledger.settled  # final receipt cannot race ahead of durable running receipt
    runtime.subagents.receipt_saved(Q.session_id,r);await c.drain()
    assert len(ledger.settled)==1 and 'completed' in ledger.settled[0][1]
    resumed=await runtime.subagents.dispatch(scope,dict(description='resume',prompt='second child',resume_agent_id=r.data['agentId']),ToolCall('second','Agent','{}'),2)
    assert resumed.data['resumed'] and resumed.data['status']=='completed'
    assert [m['content'] for m in captured[-1] if m['role']=='user']==['first child','second child']
    with pytest.raises(ValueError,match='Unknown resume'):
        await runtime.subagents.dispatch(ToolScope(runtime,c,replace(Q,session_id='foreign')),dict(description='no',prompt='no',resume_agent_id=r.data['agentId']),ToolCall('no','Agent','{}'),3)


async def test_root_guidance_fifo_consumed_once_at_next_step(tmp_path):
    entered=asyncio.Event();release=asyncio.Event();captured=[]
    class Model:
        async def complete(self,m,t,q):
            captured.append(list(m))
            if len(captured)==1:entered.set();await release.wait();return call('workspace_list')
            return ModelReply(content='guided')
    ledger=Ledger();runs=Runs(ReAct(ledger,Model(),FixedTools(),Settings('unused','unused',tmp_path)))
    stream=runs.start(Q);await entered.wait()
    assert runs.inject(Q.request_id,'first') and runs.inject(Q.request_id,'second')
    assert not runs.inject('unknown','no')
    release.set();await runs.drain()
    assert [m['content'] for m in captured[-1] if m['role']=='user']==['hello','[User guidance] first','[User guidance] second']
    assert not stream.control.injections and not runs.inject(Q.request_id,'late')


async def test_child_stop_before_coroutine_entry_settles_parent_receipt(tmp_path):
    effects=[]
    class Model:
        async def complete(self,*a):effects.append('model');return ModelReply(content='unexpected')
    ledger=Ledger();runtime=ReAct(ledger,Model(),FixedTools(),Settings('unused','unused',tmp_path))
    c=RunControl(Q,lambda e:asyncio.sleep(0));c.run=await ledger.start_run(Q);scope=ToolScope(runtime,c,Q)
    reply=await runtime.subagents.dispatch(scope,dict(description='cancel',prompt='cancel',run_in_background=True),ToolCall('parent','Agent','{}'),1)
    runtime.subagents.receipt_saved(Q.session_id,reply)
    # No yield before cancellation: child has not entered its coroutine.
    future=runtime.subagents.running[(Q.session_id,reply.data['task_id'])][0]
    future.cancel();await c.drain()
    assert not effects and ledger.background[(Q.session_id,reply.data['task_id'])]['status']=='stopped'
    assert len(ledger.settled)==1 and json.loads(ledger.settled[0][1])['status']=='stopped'
    assert not runtime.subagents.running and not runtime.subagents.agents


def test_capabilities_are_kind_scoped_and_child_snapshot(tmp_path):
    runtime=ReAct(Ledger(),object(),FixedTools(),Settings('unused','unused',tmp_path))
    c=RunControl(Q,lambda e:asyncio.sleep(0));disabled={'skill':['skill-ref'],'mcp':['mcp-ref']}
    scope=ToolScope(runtime,c,Q,disabled=disabled)
    disabled['skill'].clear()
    assert scope.denied('skill_tool',{'name':'skill-ref'})
    assert scope.denied('skill_tool',{'name':'mcp-ref'}) is None
    assert scope.denied('mcp__mcp-ref__read',{})
    assert scope.denied('mcp__skill-ref__read',{}) is None


async def test_child_tools_and_plan_tools_enforced_at_execution(tmp_path):
    ledger=Ledger();runtime=ReAct(ledger,object(),FixedTools(),Settings('unused','unused',tmp_path))
    c=RunControl(Q,lambda e:asyncio.sleep(0))
    defn=dict(allowed_tools_json=['*'],disallowed_tools_json=['workspace_write'])
    child=ToolScope(runtime,c,Q,child={'subAgentId':'child'},definition=defn)
    for name in ('Agent','AskUserQuestion','TaskStop','TaskOutput','SendMessage','EnterPlanMode','ExitPlanMode','workspace_write','memory','session_search'):
        assert child.denied(name,{})
    planner=ToolScope(runtime,c,replace(Q,agent_type=3),plan={'mode':'plan'})
    assert planner.denied('document_generate',{}) and planner.denied('workspace_write',{'path':'outside.md'})
    read_scope=ToolScope(runtime,c,Q,plan={'mode':'plan'})
    assert read_scope.denied('text_processor',{}) is None  # original Java name-based policy
    assert planner.denied('workspace_write',{'path':'.reactor/plan.md'}) is None


async def test_subagent_semaphore_is_bounded_and_release_on_cancel(tmp_path):
    entered=[];release=asyncio.Event()
    class Model:
        async def complete(self,m,t,q):entered.append(q.request_id);await release.wait();return ModelReply(content='done')
    ledger=Ledger();runtime=ReAct(ledger,Model(),FixedTools(),Settings('unused','unused',tmp_path,max_subagents=1))
    c=RunControl(Q,lambda e:asyncio.sleep(0));c.run=await ledger.start_run(Q);scope=ToolScope(runtime,c,Q)
    receipts=[]
    for i in range(2):
        r=await runtime.subagents.dispatch(scope,dict(description='bg',prompt='task',run_in_background=True),ToolCall('p'+str(i),'Agent','{}'),i)
        runtime.subagents.receipt_saved(Q.session_id,r);receipts.append(r)
    await wait_for(lambda:len(entered)==1)
    await runtime.subagents.task_tool(scope,'TaskStop',dict(task_id=receipts[0].data['task_id']))
    await wait_for(lambda:len(entered)==2)
    release.set();await c.drain()
    assert runtime.subagents.gate._value==1


@pytest.mark.parametrize('path',['../secret','/etc/passwd','skills/global.md','other/../../secret'])
def test_workspace_escape_and_shared_skill_rejected(path,tmp_path):
    ws=Workspace(tmp_path,'session')
    with pytest.raises(ValueError):ws.write(path,'bad')


def test_symlink_escape_and_per_child_read_state(tmp_path):
    a=Workspace(tmp_path,'session');b=Workspace(tmp_path,'session')
    a.write('file.md','before')
    with pytest.raises(ValueError,match='workspace_read'):b.execute('workspace_edit',dict(path='file.md',old_string='before',new_string='after'))
    b.execute('workspace_read',dict(path='file.md'));a.write('file.md','changed')
    with pytest.raises(ValueError,match='modified'):b.execute('workspace_edit',dict(path='file.md',old_string='changed',new_string='after'))
    outside=tmp_path/'outside';outside.mkdir();(outside/'secret').write_text('secret')
    (tmp_path/'session'/'escape').symlink_to(outside,target_is_directory=True)
    with pytest.raises(OSError):a.read('escape/secret')
    with pytest.raises(OSError):a.write('escape/secret','bad')
    assert (outside/'secret').read_text()=='secret'
