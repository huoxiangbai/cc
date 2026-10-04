import json
from dataclasses import replace
import httpx
import pytest
from reactor_backend.adapters.model import HTTPModel, ModelBinding, ModelFailure, ModelCatalog
from reactor_backend.bootstrap.config import Settings
from test_contracts import Q


async def test_retry_exhaustion_fallback_and_thinking():
    calls=[]
    class Catalog:
        async def chain(self,ref):
            return [ModelBinding('primary','http://provider','test-key'),ModelBinding('backup','http://provider','test-key',supports_thinking=True)]
    def respond(r):
        b=json.loads(r.content);calls.append(b)
        if b['model']=='primary': return httpx.Response(503)
        return httpx.Response(200,json={'choices':[{'message':{'content':'backup result'},'finish_reason':'stop'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as c:
        reply=await HTTPModel(c,Catalog(),retry_delay=0).complete([],[],replace(Q,thinking=True,thinking_effort='high'))
    assert len(calls)==7 and reply.model=='backup'
    assert calls[-1]['enable_thinking'] is True and calls[-1]['reasoning_effort']=='high'
    assert 'enable_thinking' not in calls[0]


@pytest.mark.parametrize('status,attempts',[ (401,2),(400,1),(422,1)])
async def test_fallback_classification(status,attempts):
    seen=[]
    class Catalog:
        async def chain(self,ref): return [ModelBinding(x,'http://provider','test-key') for x in ('a','b')]
    def respond(r):
        seen.append(json.loads(r.content)['model'])
        return httpx.Response(status)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as c:
        with pytest.raises(ModelFailure): await HTTPModel(c,Catalog(),retry_delay=0).complete([],[],Q)
    assert len(seen)==attempts


async def test_struct_parse_real_adapter_and_native_observation_text():
    sent=[]
    class Catalog:
        async def resolve(self,ref):return ModelBinding('text','http://provider','test-key',protocol='struct_parse')
    def respond(r):
        sent.append(json.loads(r.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'thought\n```json\n{"function_name":"TaskList"}\n```'},'finish_reason':'stop'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as c:
        reply=await HTTPModel(c,Catalog()).complete([{'role':'tool','tool_call_id':'a','content':'observation'}],[{'type':'function','function':{'name':'TaskList'}}],Q)
    assert reply.content=='thought' and reply.calls[0].name=='TaskList' and reply.calls[0].arguments=='{}'
    assert 'tools' not in sent[0] and sent[0]['messages'][-1]['content']=='Tool result a: observation'


async def test_empty_rescue_only_once_per_model():
    sent=[]
    class Catalog:
        async def resolve(self,ref):return ModelBinding('a','http://provider','test-key')
    def respond(r):
        sent.append(json.loads(r.content)['stream'])
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},text='data:[DONE]\n\n') if sent[-1] else httpx.Response(200,json={'choices':[]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as c:
        with pytest.raises(ModelFailure):await HTTPModel(c,Catalog(),retry_delay=0).complete([],[],Q)
    assert sent.count(False)==1 and sent.count(True)==6


async def test_catalog_duplicate_ids_enabled_defaults_fallback_chain(tmp_path):
    def row(i,usage,name): return dict(id=i,model_id='shared',model_name=name,base_url='http://provider',api_key='test-key',completions_path='',model_usage=usage,supports_thinking=1,context_window=50000)
    class Ledger:
        async def transact(self,fn):return [row(3,'fallback','backup'),row(2,'default','new'),row(1,'default','old')]
    cat=ModelCatalog(Ledger(),Settings('unused','unused',tmp_path))
    assert (await cat.resolve('shared')).model=='new'
    assert (await cat.resolve('__db_binding__:1')).model=='old'
    assert [b.model for b in await cat.chain('default')]==['new','backup']


async def test_configured_sampling_extras_and_db_window_priority(tmp_path):
    settings=Settings('unused','unused',tmp_path,model_name='configured',model_base_url='http://provider',
        llm_settings={'configured':dict(max_tokens=2048,temperature=.2,max_input_tokens=60000,
            functionCallType='struct_parse',reasoning_effort='medium',extParams={'topP':.7,'maxCompletionTokens':4096,'custom_flag':True})})
    class Ledger:
        async def transact(self,fn):return []
    binding=await ModelCatalog(Ledger(),settings).resolve('configured')
    assert binding.max_tokens==2048 and binding.temperature==.2 and binding.context_window==60000 and binding.protocol=='struct_parse'
    assert binding.extra_body==dict(top_p=.7,max_completion_tokens=4096,custom_flag=True)
    assert ModelCatalog(Ledger(),settings).parameters(binding,'configured',32000).context_window==32000
    with pytest.raises(ModelFailure):
        ModelCatalog(Ledger(),replace(settings,llm_settings={'configured':{'extParams':{'tools':[]}}})).parameters(binding,'configured')
