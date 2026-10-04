import copy
from dataclasses import replace
import pytest
from reactor_backend.memory.working import Compactor,groups,micro,threshold,tokens,fence
from reactor_backend.memory.providers import Providers
from reactor_backend.models.types import Query,ModelReply,ToolCall

Q=Query('p4-request','p4-session','visitor-a','continue','trace','user',1)


def pair(i,size=10000):
    return [{'role':'assistant','content':'call','tool_calls':[ToolCall(str(i),'real_tool','{}').wire()]},{'role':'tool','tool_call_id':str(i),'content':'真实结果'+str(i)+'x'*size}]


def test_tool_groups_reject_orphans():
    for broken in ([{'role':'tool','tool_call_id':'x','content':'orphan'}],[pair(1)[0]],pair(1)+[pair(2)[1]]):
        with pytest.raises(ValueError):groups(broken)
    assert len(groups(pair(1)+pair(2)))==2


def test_micro_pair_preserved_and_original_unchanged():
    source=pair(1)+pair(2);saved=copy.deepcopy(source);result=micro(source,1,12)
    assert result[1]['content']=='[Old tool result content cleared]'
    assert result[3]['content'].endswith('[truncated tool result]')
    assert source==saved;groups(result)


def test_java_threshold_and_fence():
    assert threshold(100000)==75000 and threshold(4000)==3400
    assert 'secret' not in fence('<analysis>secret</analysis><summary>decisions</summary>')['content']


@pytest.mark.parametrize('failure',[RuntimeError('auth 401'),TimeoutError('timeout'),RuntimeError('empty summary')])
async def test_compaction_failure_retains_usable_context(failure):
    class Model:
        async def complete(self,*args):raise failure
    source=[{'role':'system','content':'system'}]+sum([pair(i) for i in range(10)],[])+[{'role':'user','content':'最新问题'}]
    compactor=Compactor(Model(),{'micro_enabled':False,'protect_last_n':1,'summary_target_ratio':.1})
    result,event=await compactor.compact(source,[],Q,6000)
    assert event['error_message'] and event['strategy'] in ('local-fallback','drop-oldest','abort-unchanged')
    assert result[-1]['content']=='最新问题';groups(result[1:])
    if 'auth' in str(failure):assert result==source
    else:assert tokens(result)<tokens(source)
    assert source[2]['content'].startswith('真实结果0')


async def test_model_compaction_and_session_notes():
    calls=[]
    class Model:
        async def complete(self,m,t,q):calls.append((m,t,q));return ModelReply(content='<summary>旧决策路径 artifacts/report.csv</summary>')
    source=[{'role':'system','content':'system'}]+sum([pair(i) for i in range(8)],[])+[{'role':'user','content':'continue'}]
    result,event=await Compactor(Model(),{'micro_enabled':False,'protect_last_n':1}).compact(source,[],Q,5000)
    assert calls and event['strategy'] in ('full-llm','drop-oldest');groups(result[1:]);assert 'artifacts/report.csv' in str(result)
    result,event=await Compactor(Model(),{'micro_enabled':False,'protect_last_n':1,'session_memory_enabled':True,'protect_first_n':0}).compact(source,[],Q,5000,'Existing session notes')
    assert event['strategy']=='session-memory';groups(result[1:])


def test_providers_have_no_cross_owner_or_false_remote_results():
    providers=Providers({'providers':['holographic','openviking'],'openviking_endpoint':'https://unverified.invalid'})
    providers.execute('a','fact_store',{'action':'add','content':'偏好中文回答'})
    providers.execute('a','viking_memory',{'action':'remember','category':'preference','content':'Chinese reports'})
    assert providers.execute('b','fact_store',{'action':'list'})['facts']==[]
    assert providers.execute('b','viking_memory',{'action':'browse'})['buckets']=={}
    assert providers.prefetch('a','Chinese');assert 'endpoint=' not in providers.prefetch('a','Chinese')


def test_legacy_media_reasoning_and_private_metadata_wire():
    from reactor_backend.memory.working import model_messages
    source=pair(1)+[{'role':'user','content':'图片','_base64_image':'data:image/png;base64,aQ==','_origin':'private'}]
    source[0]['reasoning_content']='native reasoning'
    source[1]['_base64_image']='aQ=='
    result=model_messages(source)
    assert result[0]['reasoning_content']=='native reasoning'
    assert result[1]['role']=='tool' and result[2]['content'][0]['text'].startswith('[tool image]')
    assert result[3]['content'][1]['image_url']['url']=='data:image/png;base64,aQ=='
    assert all(not any(k.startswith('_') for k in m) for m in result)
