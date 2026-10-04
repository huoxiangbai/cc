import asyncio
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import httpx
import pytest
from reactor_backend.models.types import Query, ModelReply, ToolCall, ToolReply
from reactor_backend.application.query import normalize
from reactor_backend.application.runs import RunStream, Runs
from reactor_backend.bootstrap.config import Settings
from reactor_backend.projection.events import frame,wire,Projector
from reactor_backend.projection.history import history_view
from reactor_backend.adapters.model import HTTPModel,ModelBinding,ModelFailure,ModelCatalog
from reactor_backend.adapters.tool_api import ToolAPI
from reactor_backend.runtime.react import ReAct

ROOT=Path(__file__).resolve().parents[2]
GOLD=json.loads((ROOT/'docs/python-migration/fixtures/java-behavior.json').read_text())
Q=Query('request-p1','session-p1','visitor-p1','hello','trace','reactor',5)

@pytest.mark.parametrize('deep',[0,1,-1])
def test_p0_normalization(deep):
    q=normalize(dict(query='中文',requestId='  req-p0  ',sessionId='session-p0',deepThink=deep),'visitor-p0')
    expected=GOLD['serialization'][f'request-{deep}']
    assert q.agent_type == expected['agentType']
    assert q.request_id == expected['requestId']
    assert q.user == expected['erp']
    assert q.model is None and q.output_style is None
    defaults=normalize(dict(requestId='req-p0',sessionId='session-p0'),'visitor-p0')
    assert defaults.trace_id == GOLD['serialization']['normalized-defaults']['traceId']


def test_exact_builder_nulls_and_data_only_utf8():
    assert frame() == GOLD['serialization']['gpt-builder']
    encoded=wire(frame('中文',status='success'))
    assert b'event:' not in encoded and b'id:' not in encoded and b'[DONE]' not in encoded
    assert encoded.startswith(b'data:') and encoded.endswith(b'\n\n')
    assert json.loads(encoded.decode().split('data:',1)[1])['reqId'] == '中文'


def test_observation_cap_and_error():
    assert ToolReply(data={'tool':'real','ok':False},failed=False).observation() == '{"tool":"real","ok":false}'
    assert ToolReply(failed=True,error='timeout').observation() == 'Error: timeout'
    assert json.loads(ToolReply(data={'type':'tool_error'},failed=True,error='timeout').observation())['tool_ok'] is False
    assert 'output truncated' in ToolReply(data='x'*96001).observation()


def test_old_java_history_golden():
    at=datetime(2026,10,2,22)
    session=dict(session_id='session-history-p0',title='中文历史',status=1,run_count=1,finished_run_count=1,failed_run_count=0,started_at=at,last_active_at=at.replace(second=3))
    run=dict(id=1,request_id='req-history-p0',entry_agent='react',status=1,query_text='中文历史',final_summary_text='history summary',started_at=at,finished_at=at.replace(second=3))
    tool=dict(id=1,llm_invocation_id=None,tool_call_id='req-history-p0-tool-1',tool_name='file_tool',input_json='{"requestId":"req-history-p0"}',llm_oberserve='done',finished_at=at.replace(second=2))
    artifact=dict(tool_invocation_id=1,file_name='report-p0.md',storage_key='oss://report-p0.md',download_url='https://file.example.com/download/report-p0.md',preview_url='https://file.example.com/preview/report-p0.md',mime_type=None,file_size=None)
    result=history_view(session,[dict(run=run,llms=[],tools=[tool],artifacts=[artifact])])
    expected=json.loads(GOLD['history']['detail']['body'])['data']
    for x in (result,expected):
        for f in x['runs'][0]['replayFrames']:
            f['resultMap']['eventData']['taskId']='dynamic-task'
    assert result == expected


class BindingCatalog:
    async def resolve(self,ref):
        return ModelBinding('test','http://model','test-key')

@pytest.mark.parametrize('case',['stream','retry','auth','empty_rescue','truncated'])
async def test_provider_adapter(case):
    attempts=[]
    def respond(request):
        body=json.loads(request.content); attempts.append(body)
        if case == 'auth': return httpx.Response(401,json={'error':'no'})
        if case == 'retry' and len(attempts)==1: return httpx.Response(503)
        if case == 'truncated': return httpx.Response(200,headers={'Content-Type':'text/event-stream'},text='data:{"choices":[{"delta":{"content":"partial"}}]}\n\n')
        if case == 'empty_rescue' and body['stream']:
            return httpx.Response(200,headers={'Content-Type':'text/event-stream'},text='data:[DONE]\n\n')
        if not body['stream']:
            return httpx.Response(200,json={'choices':[{'message':{'content':'rescued'},'finish_reason':'stop'}]})
        data=[{'choices':[{'delta':{'content':'中文','tool_calls':[{'index':0,'id':'call','function':{'name':'text_processor','arguments':'{"operation":'}}]}}]},
              {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'arguments':'"read"}'}}]},'finish_reason':'tool_calls'}],'usage':{'total_tokens':9}}]
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},text=''.join('data:'+json.dumps(x)+'\n\n' for x in data)+'data:[DONE]\n\n')
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        adapter=HTTPModel(client,BindingCatalog(),retry_delay=0)
        if case in ('auth','truncated'):
            with pytest.raises(ModelFailure): await adapter.complete([],[],Q)
            assert len(attempts)==(1 if case=='auth' else 6)
        else:
            result=await adapter.complete([],[],Q)
            assert result.content == ('rescued' if case=='empty_rescue' else '中文')
            if case != 'empty_rescue':
                assert result.calls[0] == ToolCall('call','text_processor','{"operation":"read"}')
                assert result.usage['total_tokens']==9
            assert len(attempts)==(2 if case in ('retry','empty_rescue') else 1)

@pytest.mark.parametrize('case',['timeout','business','invalid_json','structured'])
async def test_remote_tool_adapter(case,tmp_path):
    async def respond(request):
        sent=json.loads(request.content)
        assert sent['requestId'] == Q.session_id
        assert sent['workspace_root'] == str(tmp_path/Q.session_id)
        if case=='timeout': await asyncio.sleep(.1)
        if case=='business': return httpx.Response(400,json={'success':False,'message':'real tool failure'})
        if case=='invalid_json': return httpx.Response(200,text='broken')
        return httpx.Response(200,json={'success':True,'message':'ok','data':{'values':[1,2]}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        adapter=ToolAPI(client,'http://tool',tmp_path,timeout=.01)
        reply=await adapter.execute('text_processor',{},Q)
        assert reply.failed == (case != 'structured')
        assert reply.timed_out == (case == 'timeout')
        if case=='structured': assert reply.structured_output['data']['values'] == [1,2]


async def test_bounded_buffer_cursor_and_disconnect():
    stream=RunStream(Q)
    p=Projector(Q.request_id)
    for i in range(140): await stream.publish(p.event('tool_thought',str(i),{'toolThought':str(i)}))
    assert len(stream.buffer)==128
    q=stream.attach(138)
    assert [q.get_nowait()['eventSeq'],q.get_nowait()['eventSeq']] == [139,140]
    stream.observers.discard(q)
    await stream.publish(p.event('result','final',{'result':'done'},finished=True))
    assert not stream.closed


class MemoryLedger:
    def __init__(self): self.llms=[];self.tools=[];self.finished=[];self.context_messages=[]
    async def start_run(self,q): return {'id':1,'request_id':q.request_id,'session_id':q.session_id}
    async def context(self,s): return self.context_messages
    async def start_llm(self,*args): self.llms.append(args);return len(self.llms)
    async def finish_llm(self,*args): pass
    async def start_tool(self,*args): self.tools.append(args);return len(self.tools)
    async def finish_tool(self,*args): pass
    async def register_artifacts(self,*args): return []
    async def finish_run(self,*args): self.finished.append(args)

class FixedModel:
    def __init__(self, replies): self.replies=iter(replies);self.messages=[]
    async def complete(self,messages,tools,q):
        import copy
        self.messages.append(copy.deepcopy(messages))
        result=next(self.replies)
        if isinstance(result,Exception): raise result
        return result

class FixedTools:
    schemas=[]
    async def execute(self,name,args,q):
        await asyncio.sleep(.01 if args.get('slow') else 0)
        return ToolReply(data={'tool':name,'ok':True,'value':args})

@pytest.mark.parametrize('case',['multiround','bad_arguments','model_failure','budget'])
async def test_react_loop(case,tmp_path):
    ledger=MemoryLedger()
    calls=[ToolCall('one','text_processor','{"slow":true}'),ToolCall('two','text_processor','{}')]
    replies=[ModelReply(content='think',calls=calls),ModelReply(calls=[ToolCall('three','text_processor','{}')]),ModelReply(content='final')]
    if case=='bad_arguments': replies=[ModelReply(calls=[ToolCall('bad','text_processor','invalid-json')]),ModelReply(content='error handled')]
    if case=='model_failure': replies=[RuntimeError('model unavailable')]
    if case=='budget': replies=[ModelReply(calls=calls)]
    model=FixedModel(replies)
    runtime=ReAct(ledger,model,FixedTools(),Settings('unused','unused',tmp_path,max_steps=1 if case=='budget' else 5))
    events=[]
    async def publish(e): events.append(e)
    await runtime.execute(Q,publish)
    assert ledger.finished[0][1] == (2 if case in ('model_failure','budget') else 1)
    assert events[-1]['finished']
    if case=='multiround':
        assert [m['tool_call_id'] for m in model.messages[1] if m['role']=='tool'] == ['one','two']
        assert len(ledger.tools)==3 and len(ledger.llms)==3
        assert ledger.finished[0][2]=='final'
    if case=='bad_arguments': assert 'Invalid tool arguments' in model.messages[1][-1]['content']


async def test_single_visitor_gate_and_supervisor_disconnect(tmp_path):
    class Runtime:
        async def execute(self,q,publish):
            await asyncio.sleep(.04)
            await publish(frame(q.request_id,'success',True,eventSeq=1))
    runs=Runs(Runtime())
    s=runs.start(Q)
    with pytest.raises(ValueError): runs.start(replace(Q,request_id='other'))
    observer=s.attach();s.observers.discard(observer)
    await runs.drain()
    assert s.closed and s.buffer[-1]['finished'] and not runs.active


def test_single_worker_env(monkeypatch):
    monkeypatch.setenv('WEB_CONCURRENCY','2')
    with pytest.raises(ValueError,match='single'): Settings.from_env()


def test_genui_old_input_and_typed_output_replay():
    from reactor_backend.projection.genui import tree,patch,recover
    normalized=tree({'type':'Stat','nodeId':'legacy','text':'中文','children':[None]})
    assert normalized=={'schemaVersion':'1','root':{'kind':'Stat','nodeId':'legacy','props':{'text':'中文','value':'中文'},'children':[]}}
    assert patch({'patches':[{'op':'remove','path':'/root/props/value','unknown':True}]})=={'patches':[{'op':'remove','path':'/root/props/value'}]}
    with pytest.raises(ValueError): tree({'kind':'arbitrary script'})
    with pytest.raises(ValueError): patch({'patches':[{'op':'replace','path':'root','value':1}]})
    invocation={'tool_name':'emit_ui_tree','tool_call_id':'call-old','structured_output':{'tree_json':json.dumps(normalized),'canvas_id':'canvas-old'}}
    kind,value=recover(invocation,{})
    assert kind=='ui_tree' and value['canvas_id']=='canvas-old' and value['tree']==normalized
    at=datetime(2026,10,2,22)
    facts=dict(run=dict(request_id='req-genui',status=1,started_at=at),llms=[],artifacts=[],tools=[dict(invocation,id=1,llm_invocation_id=None,input_json='{}',finished_at=at)])
    from reactor_backend.projection.history import replay
    data=replay(facts)[0]['resultMap']['eventData']['resultMap']
    assert data['messageType']=='ui_tree' and data['finish'] is False and data['resultMap']['tree']==normalized


def test_single_worker_guard(tmp_path):
    from reactor_backend.bootstrap.ownership import single_worker
    with single_worker(tmp_path):
        with pytest.raises(RuntimeError):
            with single_worker(tmp_path): pytest.fail('second owner admitted')
    with single_worker(tmp_path):
        assert (tmp_path/'.reactor-backend.lock').is_file()


async def test_duplicate_request_does_not_replace_active_owner():
    class Runtime:
        async def execute(self,q,publish): await asyncio.Event().wait()
    runs=Runs(Runtime())
    first=runs.start(Q)
    with pytest.raises(ValueError): runs.start(replace(Q,visitor_id='other-visitor'))
    assert runs.active[Q.request_id] is first
    first.task.cancel()
    await asyncio.gather(first.task,return_exceptions=True)


def test_artifact_old_workspace_metadata():
    from reactor_backend.delivery.artifacts import artifact_ref
    a=dict(file_name='报告.md',metadata_json='{"description":"workspace:./docs\\\\报告.md"}')
    assert artifact_ref(a)['relativePath']=='docs/报告.md'
    assert artifact_ref(dict(a,metadata_json='not json'))['relativePath']=='报告.md'


async def test_parallel_failure_settles_all_tools_before_run_commit(tmp_path):
    ledger=MemoryLedger()
    completed=[]
    class Tools(FixedTools):
        async def execute(self,name,args,q):
            if args.get('fail'): raise RuntimeError('adapter failed')
            await asyncio.sleep(.025)
            completed.append('slow finished')
            return ToolReply(data='real observation')
    model=FixedModel([ModelReply(calls=[ToolCall('fast','text_processor','{"fail":true}'),ToolCall('slow','text_processor','{}')])])
    runtime=ReAct(ledger,model,Tools(),Settings('unused','unused',tmp_path))
    async def publish(event): pass
    await runtime.execute(Q,publish)
    assert completed==['slow finished'] and ledger.finished[0][1]==2
    assert ledger.finished[0][-1]==[{'role':'user','content':'hello'}]


async def test_database_model_binding_original_trim_path_and_sampling(tmp_path):
    class Ledger:
        async def transact(self,fn):
            return [dict(id=7,model_id=' selected ',model_name=' upstream ',base_url=' http://model/v1 ',api_key=' test-key ',
                completions_path='  ',model_usage='default',supports_thinking=0,context_window=None)]
    binding=await ModelCatalog(Ledger(),Settings('unused','unused',tmp_path)).resolve(' selected ')
    assert binding.model=='upstream' and binding.base_url=='http://model/v1' and binding.path=='/chat/completions'
    assert binding.api_key=='test-key' and binding.max_tokens==16384 and binding.temperature==0.0
    received=[]
    def upstream(request):
        received.append((str(request.url),json.loads(request.content)))
        return httpx.Response(200,json={'choices':[{'message':{'content':'actual HTTP result'},'finish_reason':'stop'}]})
    class Catalog:
        async def resolve(self,ref): return binding
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as c:
        reply=await HTTPModel(c,Catalog()).complete([],[],Q)
    assert reply.content=='actual HTTP result'
    assert received[0][0]=='http://model/v1/chat/completions'
    assert received[0][1]['max_tokens']==16384 and received[0][1]['temperature']==0.0
