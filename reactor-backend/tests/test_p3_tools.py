import asyncio
from dataclasses import replace
import json
from pathlib import Path
import httpx
import pytest
from reactor_backend.adapters.tool_api import ToolAPI
from reactor_backend.adapters.tool_stream import events
from reactor_backend.adapters.web_search import WebSearch
from reactor_backend.bootstrap.config import Settings
from reactor_backend.models.types import Query,ModelReply
from reactor_backend.data_query.service import DataQuery
from reactor_backend.data_query.sql import resolve,select_sql

Q=Query('req','sess','visitor','question','trace','reactor',5)
S=Settings('mysql+pymysql://root@/test','http://tool',Path('/tmp/p3-workspace'))
MODELS=[{'modelCode':'sales-model','modelName':'销售','type':'table','content':'sales','schemaList':[
    {'modelCode':'sales-model','columnId':'category','columnName':'分类','dataType':'STRING'},
    {'modelCode':'sales-model','columnId':'amount','columnName':'金额','dataType':'DECIMAL','defaultRecall':1}]}]


def sse(items,done=True):
    return ''.join('data: '+json.dumps(x,ensure_ascii=False)+'\r\n\r\n' for x in items)+('data: [DONE]\r\n\r\n' if done else '')

@pytest.mark.parametrize('case',['ok','cut','error','invalid','timeout','cancel'])
async def test_deepsearch_stream_and_files(case,tmp_path):
    received=[];calls=[]
    stages=[{'messageType':'extend','isFinal':False,'query':'research','searchResult':{'query':['q'],'docs':[]}},
            {'messageType':'search','isFinal':False,'searchResult':{'query':['q'],'docs':[[{'title':'source','link':'https://example.org/a','content':'evidence'},{'title':'dup','link':'https://example.org/a','content':'evidence'}]]}},
            {'messageType':'chapter_summary','chapterId':'c1','chapterTitle':'章节','chapterOrder':1,'chapterSummary':'evidence from source','isFinal':False},
            {'messageType':'report','answer':'part ','isFinal':False}, {'messageType':'report','answer':'full report https://example.org/a','isFinal':True,'unknownField':'retained'}]
    async def upstream(r):
        calls.append((r.url.path,json.loads(r.content)))
        if r.url.path.endswith('/upload_file'):
            name=json.loads(r.content)['fileName'];return httpx.Response(200,json={'ossUrl':'http://tool/download/'+name,'domainUrl':'http://tool/preview/'+name})
        if case=='timeout':raise httpx.ReadTimeout('fixture')
        if case=='cancel':raise asyncio.CancelledError()
        if case=='error':return httpx.Response(503)
        if case=='invalid':return httpx.Response(200,text='data: broken\n\n')
        return httpx.Response(200,text=sse(stages,case!='cut'),headers={'Content-Type':'text/event-stream'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        api=ToolAPI(client,'http://tool',tmp_path,settings=S)
        async def emit(k,p):received.append((k,p))
        if case=='cancel':
            with pytest.raises(asyncio.CancelledError):await api.execute_scoped('deep_search',{'query':'research','reportFileName':'report.md'},Q,emit)
            return
        reply=await api.execute_scoped('deep_search',{'query':'research','reportFileName':'report.md'},Q,emit)
        assert reply.failed==(case!='ok');assert reply.timed_out==(case=='timeout')
        assert calls[0][0]=='/v1/tool/deepsearch' and calls[0][1]['request_id']==Q.session_id
        if case=='ok':
            assert [x[1]['messageType'] for x in received]==['extend','search','chapter_summary','report','report']
            assert received[-1][1]['unknownField']=='retained'
            assert len(reply.data['search_results'][0]['docs'])==1
            assert len(reply.files)==2
            assert calls[-1][1]['content']=='full report https://example.org/a'
            assert 'chapter_summary' in reply.structured_output['stages_json']
        else:assert not any(p.endswith('/upload_file') for p,_ in calls)

@pytest.mark.parametrize('name,path,items,expected',[('code_interpreter','code_interpreter',[{'code':'print(3)','isFinal':False},{'data':'progress','isFinal':False},{'codeOutput':'3','data':'3','isFinal':True}],'code_output'),
    ('data_analysis','auto_analysis',[{'data':'progress','isFinal':False},{'data':'analysis report','isFinal':True,'file_info':[]}],'content'),
    ('multimodalagent_tool','mragQuery',[{'stage':'search','data':'Searching'},{'choices':[{'delta':{'content':'knowledge'},'finishReason':None}]},{'stage':'final','isFinal':True}],'markdown_content')])
async def test_other_tool_streams(name,path,items,expected,tmp_path):
    calls=[]
    def upstream(r):
        calls.append(r.url.path)
        if r.url.path.endswith('/upload_file'):return httpx.Response(200,json={'ossUrl':'http://tool/down','domainUrl':'http://tool/prev'})
        return httpx.Response(200,text=sse(items))
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as c:
        reply=await ToolAPI(c,'http://tool',tmp_path,settings=S).execute_scoped(name,{'task':'test'},Q,None)
    assert not reply.failed and reply.structured_output[expected]
    assert calls[0]=='/v1/tool/'+path

@pytest.mark.parametrize('name,items',[('data_analysis',[{'data':{'error':'failed'},'isFinal':True}]),('multimodalagent_tool',[{'stage':'error','data':'failed','isFinal':True},{'choices':[{'delta':{'content':'failed'},'finishReason':'stop'}]}])])
async def test_error_final_is_not_success(name,items,tmp_path):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,text=sse(items)))) as c:
        assert (await ToolAPI(c,'http://tool',tmp_path,settings=S).execute_scoped(name,{},Q,None)).failed

@pytest.mark.parametrize('platform',['twitter','reddit','xueqiu'])
async def test_social_business_failure(platform,tmp_path):
    def upstream(r):
        assert r.url.path=='/v1/tool/'+platform
        assert json.loads(r.content)['requestId']=='sess'
        return httpx.Response(200,json={'code':200,'data':{'ok':False,'platform':platform,'error':{'code':'AUTH_REQUIRED','message':'credentials unavailable'}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as c:
        reply=await ToolAPI(c,'http://tool',tmp_path).execute_scoped(platform,{'operation':'search','query':'sample'},Q,None)
    assert reply.failed and reply.error=='credentials unavailable'

@pytest.mark.parametrize('provider',['grok','gpt','exa','tavily','brave'])
async def test_search_channels(provider):
    calls=[]
    def upstream(r):
        calls.append(r)
        if provider in ('gpt','grok'):return httpx.Response(200,json={'output_text':'summary','citations':['https://allowed.test/a','https://blocked.test/a']})
        hits=[{'title':'allowed','url':'https://allowed.test/a','text':'source'},{'title':'blocked','url':'https://blocked.test/a','text':'other'}]
        return httpx.Response(200,json={'web':{'results':hits}} if provider=='brave' else {'results':hits})
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as c:
        reply=await WebSearch(c,{'provider':provider,provider:{'api_key':'fixture'}}).execute({'query':'actual question','allowed_domains':['allowed.test']})
    assert not reply.failed and reply.data['provider']==provider
    assert [h['url'] for h in reply.data['hits']]==['https://allowed.test/a']
    assert calls[0].headers.get('authorization') or calls[0].headers.get('x-api-key') or calls[0].headers.get('x-subscription-token')

async def test_search_fallback_and_no_config():
    calls=[]
    def upstream(r):
        calls.append(r.url.host)
        if r.url.host=='api.x.ai':return httpx.Response(502)
        return httpx.Response(200,json={'results':[{'url':'https://source.test/','title':'source','text':'evidence'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as c:
        reply=await WebSearch(c,{'grok':{'api_key':'fixture'},'exa':{'api_key':'fixture'}}).execute({'query':'fallback question'})
        assert reply.data['provider']=='exa' and reply.structured_output['provider_failures']==[{'provider':'grok','error':'HTTPStatusError'}]
        assert (await WebSearch(c,{}).execute({'query':'question'})).failed
    assert calls==['api.x.ai','api.x.ai','api.exa.ai']

@pytest.mark.parametrize('sql',["DELETE FROM `sales-model`","SELECT * FROM `sales-model`; DROP TABLE sales", "SELECT * INTO OUTFILE 'file' FROM `sales-model`",'SELECT * FROM other'])
def test_sql_rejects_non_query_or_unknown_model(sql):
    with pytest.raises((ValueError,Exception)):resolve(sql,MODELS,'mysql')


def test_sql_ast_replacement_aggregation_literal_and_filters():
    sql,cols,filters,dims,measures=resolve("SELECT category, SUM(amount) AS total FROM `sales-model` WHERE category = 'sales-model' GROUP BY category ORDER BY total DESC",MODELS,'mysql')
    assert "FROM sales" in sql and "'sales-model'" in sql
    assert dims==['category'] and measures==['total']
    assert cols[1]['agg']=='SUM' and cols[1]['order']=='DESC'
    assert filters[0]['val']=='sales-model'


async def test_tablerecall_fallback_merge_nl2sql_execute_export():
    calls=[];executed=[]
    class Catalog:
        async def models(self):return json.loads(json.dumps(MODELS))
    class DB:
        type='mysql'
        async def query(self,sql):executed.append(sql);return {'dataList':[{'category':'A','total':12.5}],'dataSize':1}
    def upstream(r):
        calls.append(r.url.path);body=json.loads(r.content)
        if r.url.path.endswith('/table_rag'):return httpx.Response(200,json={'code':200,'data':[{'schemaList':[MODELS[0]['schemaList'][0]]}]})
        if r.url.path.endswith('/nl2sql'):
            assert len(body['schemaInfo'][0]['schemaList'])==2
            return httpx.Response(200,json={'code':200,'data':[{'query':'sales','nl2sql':'SELECT category, SUM(amount) AS total FROM `sales-model` GROUP BY category'}]})
        return httpx.Response(200,json={'ossUrl':'http://tool/download/'+body['fileName'],'domainUrl':'http://tool/preview/'+body['fileName']})
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as c:
        api=ToolAPI(c,'http://tool',Path('/tmp'))
        req,result,files=await DataQuery(Catalog(),DB(),api,{'es':{'enable':True}}).query('sales')
    assert len(executed)==1 and 'FROM sales' in executed[0]
    assert result[0]['measureCols']==['total'] and len(files)==3
    assert calls[:2]==['/v1/tool/table_rag','/v1/tool/nl2sql']

@pytest.mark.parametrize('case',['ok','extract_error','redirect','invalid','http_error'])
async def test_webfetch_original_file_and_extraction_contract(case,tmp_path):
    from reactor_backend.adapters.web_fetch import WebFetch
    calls=[]
    class Model:
        async def complete(self,messages,tools,q):
            assert 'full original body' in messages[1]['content']
            if case=='extract_error':raise ValueError('fixture unavailable')
            return ModelReply(content='extracted with https://source.test/page')
    def upstream(r):
        calls.append((r.method,str(r.url)))
        if r.method=='GET':
            if case=='redirect':return httpx.Response(302,headers={'Location':'https://other.test/page'})
            if case=='http_error':return httpx.Response(404)
            return httpx.Response(200,text='original body')
        return httpx.Response(200,json={'code':200,'data':{'content':'full original body','finalUrl':'https://source.test/page'},
            'fileInfo':[{'fileName':'source.md','ossUrl':'http://tool/full','domainUrl':'http://tool/view'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as c:
        result=await WebFetch(ToolAPI(c,'http://tool',tmp_path),Model()).execute({'url':'ftp://source.test/' if case=='invalid' else 'http://source.test/page','prompt':'extract'},Q)
    assert result.failed==(case in ('invalid','http_error'))
    if case=='redirect':assert result.data['redirectUrl']=='https://other.test/page' and len(calls)==1
    elif not result.failed:
        assert len(result.files)==1 and result.structured_output['data']['content']=='full original body'
        assert result.data['degraded']==(case=='extract_error')
        assert calls[0][1]=='https://source.test/page'

async def test_real_recall_protocols_and_clickhouse_execution():
    from reactor_backend.adapters.business_db import BusinessDB
    calls=[]
    def upstream(r):
        calls.append(r)
        if r.url.path.endswith('/embedding/text'):return httpx.Response(200,json={'vectors':[[.1,.2,.3]]})
        if r.url.path.endswith('/points/search'):
            assert json.loads(r.content)['filter']['must'][0]['match']['any']==['sales-model']
            return httpx.Response(200,json={'result':[{'id':'stable-uuid','score':.8,'payload':{'columnId':'category'}}]})
        if r.url.path.endswith('/_search'):return httpx.Response(200,json={'hits':{'hits':[{'_source':{'value':'A'},'_score':2.0}]}})
        assert r.content.decode().endswith(' FORMAT JSON')
        return httpx.Response(200,json={'data':[{'total':37.5}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as c:
        service=DataQuery(None,None,ToolAPI(c,'http://tool',Path('/tmp')),{'qdrant':{'enable':True,'url':'http://vectors'},'es':{'enable':True,'url':'http://elastic'}})
        assert (await service.vector({'query':'sales','modelCodeList':['sales-model']}))[0]['_id']=='stable-uuid'
        assert (await service.elastic({'query':'A','modelCodeList':['sales-model']}))[0]['_score']==2.0
        assert (await BusinessDB({'type':'clickhouse','url':'http://business'},c).query('SELECT SUM(amount) AS total FROM sales'))['dataList']==[{'total':37.5}]

@pytest.mark.parametrize('sql',["WITH c AS (SELECT category, amount FROM `sales-model`) SELECT category, SUM(amount) AS total FROM c GROUP BY category", "SELECT category, amount FROM `sales-model` UNION ALL SELECT category, amount FROM `sales-model`"])
def test_original_union_cte_query_shapes(sql):
    actual,cols,_,_,_=resolve(sql,MODELS,'mysql')
    assert 'sales-model' not in actual and 'sales' in actual and cols

async def test_bash_preserves_exit_timeout_and_output(tmp_path):
    def upstream(r):
        b=json.loads(r.content);assert b['workspaceRoot']==str(tmp_path/'sess') and b['skillLibraryRoot'] is None
        return httpx.Response(200,json={'exitCode':7,'stdout':'actual stdout','stderr':'actual error','timedOut':False,'durationMs':12})
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as c:
        r=await ToolAPI(c,'http://tool',tmp_path).execute('bash',{'command':'exit 7'},Q)
    assert not r.failed and r.data['exit_code']==7 and r.data['stdout']=='actual stdout'

@pytest.mark.parametrize('entry',json.loads((Path(__file__).resolve().parents[2]/'docs/python-migration/fixtures/p3-sql-java.json').read_text())+json.loads((Path(__file__).resolve().parents[2]/'docs/python-migration/fixtures/p3-sql-java-unaliased.json').read_text()))
def test_original_java_query_column_and_filter_contract(entry):
    _,columns,filters,_,_=resolve(entry['sql'],MODELS,'mysql')
    assert columns==entry['columns']
    assert filters==entry['filters']
