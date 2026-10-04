"""Real protected facade, original Tool, MySQL owner maps and SQLite business."""
import json
from contextlib import contextmanager
import os
import httpx
from sqlalchemy import text
from test_integration import env,client


@contextmanager
def other(env):
    with httpx.Client(base_url=env[1],trust_env=False,timeout=30) as c:
        c.get('/api/agent/visitor/bootstrap')
        yield c


def test_closure_tool_internal_auth_and_no_identity(env):
    with httpx.Client(base_url=env[2],trust_env=False) as c:
        assert c.post('/v1/file_tool/upload_file',json={'requestId':'evil','fileName':'x','content':'x','description':'x'}).status_code==403
        assert c.get('/_reactor/security',headers={'X-Reactor-Service-Token':'wrong'}).status_code==403
    with httpx.Client(base_url=env[1],trust_env=False) as c:
        assert c.post('/v1/documents/list_knowledge_base',json={}).status_code==403
        assert c.get('/data/allModels').status_code==403
        assert c.post('/data/apiChatQuery',headers={'X-Reactor-Service-Token':os.environ['P1_TEST_SERVICE_TOKEN']},json={'content':'P3'}).status_code==403


def test_closure_file_upload_download_filters_and_legacy(env,client):
    result=client.post('/v1/file_tool/upload_file',json={'requestId':'closure-upload','fileName':'来源.md','description':'来源','content':'真实私有文件','owner':'forged'})
    assert result.status_code==200,result.text
    data=result.json();assert client.get(data['domainUrl']).text=='真实私有文件'
    with other(env) as b:
        assert b.get(data['downloadUrl']).status_code==403
        assert b.post('/v1/file_tool/upload_file',json={'requestId':'closure-upload','fileName':'来源.md','description':'','content':'覆盖','owner':client.get('/api/agent/visitor/bootstrap').json()['data']['visitorId']}).status_code==403
        own=b.post('/v1/file_tool/upload_file',json={'requestId':'closure-b','fileName':'b.txt','description':'','content':'B'});assert own.status_code==200
        assert b.post('/v1/file_tool/get_file_list',json={'requestId':'closure-b','filters':[{'requestId':'closure-upload','fileName':'来源.md'}]}).status_code==403
    internal={'X-Reactor-Service-Token':os.environ['P1_TEST_SERVICE_TOKEN']}
    r=httpx.post(env[2]+'/v1/file_tool/upload_file',json={'requestId':'legacy-unowned','fileName':'old.txt','description':'','content':'old'},headers=internal,trust_env=False)
    assert r.status_code==200
    for action in ('get_file_list','upload_file'):
        assert client.post('/v1/file_tool/'+action,json={'requestId':'legacy-unowned','fileName':'old.txt','description':'','content':'claim'}).status_code==403
    assert client.post('/v1/file_tool/register_file',json={'requestId':'closure-upload','fileName':'x','localPath':'/etc/passwd'}).status_code==403
    (env[0]/'p3-closure-acl-evidence.json').write_text(json.dumps({'file':data,'crossVisitor':'403','forgedOwner':'403','legacy':'403','filterBypass':'403'},ensure_ascii=False,indent=2))


def test_closure_kb_document_upload_scope_history_and_failures(env,client):
    r=client.post('/v1/documents/create_knowledge_base',json={'kb_name':'SQLite权限证据库'});assert r.status_code==200,r.text
    kb=r.json()['data']['kb_id']
    uploaded=client.post('/v1/documents/upload',files={'file':('来源.txt','SQLite业务来源'.encode(),'text/plain')})
    assert uploaded.status_code==200,uploaded.text
    u=uploaded.json()['data']
    assert client.get(u['preview_url']).status_code==200
    sid=client.post('/v1/mrag/sessions/create',json={'kb_id':kb,'title':'权限历史'}).json()['data']['session_id']
    with other(env) as b:
        listing=b.post('/v1/documents/list_knowledge_base',json={}).json()['data']['list']
        assert kb not in [k['kb_id'] for k in listing]
        for path,body in [
            ('list_kb_files',{'kb_id':kb}),('get_file_full_content',{'kb_id':kb,'file_id':'x'}),
            ('delete_files',{'kb_id':kb,'file_ids':['x']}),('delete_knowledge_base',{'kb_id':kb}),
            ('add_files',{'kb_id':kb,'files':[]}),('create_knowledge_base',{'kb_id':kb,'kb_name':'覆盖'})]:
            assert b.post('/v1/documents/'+path,json=body).status_code==403
        assert b.get(u['permanent_url']).status_code==403
        assert b.post('/v1/mrag/sessions/detail',json={'session_id':sid}).status_code==403
        assert b.post('/v1/mrag/sessions/delete',json={'session_id':sid}).status_code==403
        bkb=b.post('/v1/documents/create_knowledge_base',json={'kb_name':'B库'}).json()['data']['kb_id']
        assert b.post('/v1/documents/add_files',json={'kb_id':bkb,'files':[{'filename':u['filename'],'file_url':u['permanent_url'],'file_type':'file'}]}).status_code==403
    assert client.post('/v1/documents/list_kb_files',json={'kb_id':kb}).status_code==200
    assert client.post('/v1/mrag/sessions/detail',json={'session_id':sid}).status_code==200
    assert client.post('/v1/mrag/sessions/delete',json={'session_id':sid}).status_code==200
    # Real missing external Qdrant failure cannot be mistaken for successful deletion.
    deletion=client.post('/v1/documents/delete_knowledge_base',json={'kb_id':kb})
    assert deletion.status_code>=400


def test_closure_sqlite_metadata_init_and_query_artifacts(env,client):
    models=client.get('/data/allModels').json()['data']
    sales=next(m for m in models if m['modelCode']=='sales-model')
    assert sales['schemaList'] and next(s for s in sales['schemaList'] if s['columnId']=='category')['defaultRecall']==1
    with env[3].connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM chat_model_info WHERE code='sales-model' AND yn=1")).scalar()==1
    r=client.post('/data/chatQuery',json={'content':'P3 查询各分类销售额'})
    frames=[json.loads(x[5:]) for x in r.text.splitlines() if x.startswith('data:')]
    assert next(f['data'] for f in frames if f['eventType']=='CHART_DATA')[0]['dataList']==[{'category':'A','total':30},{'category':'B','total':7.5}]
    rid=next(f['data'] for f in frames if f['eventType']=='DEBUG')
    files=client.post('/v1/file_tool/get_file_list',json={'requestId':rid}).json()['results']
    assert len(files)==3
    with other(env) as b:
        for f in files:assert b.get(f['domainUrl']).status_code==403
    with env[3].connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM reactor_private_resource_owner WHERE resource_kind='data_query' AND resource_key=:rid"),{'rid':rid}).scalar()==1


async def test_closure_metadata_refresh_sql_model_failure_keeps_active_rows(env):
    from reactor_backend.adapters.mysql import MySQLLedger
    from reactor_backend.adapters.data_catalog import DataCatalog
    from reactor_backend.adapters.business_db import BusinessDB
    from types import SimpleNamespace
    import pytest
    cfg=json.loads((env[0]/'data-config.json').read_text())
    ledger=MySQLLedger(os.environ['P1_TEST_MYSQL_URL'])
    async with httpx.AsyncClient(trust_env=False) as http:
        api=SimpleNamespace(client=http,base_url=env[2],headers={'X-Reactor-Service-Token':os.environ['P1_TEST_SERVICE_TOKEN']})
        db=BusinessDB(cfg['db'],http);catalog=DataCatalog(ledger)
        try:
            with env[3].connect() as c:before=c.execute(text("SELECT id FROM chat_model_info WHERE code='sales-model' AND yn=1")).scalar()
            await catalog.initialize(db,api,cfg)
            with env[3].connect() as c:assert c.execute(text("SELECT id FROM chat_model_info WHERE code='sales-model' AND yn=1")).scalar()==before
            refresh={**cfg,'forceRefresh':True,'modelList':[dict(cfg['modelList'][0],ignoreFields='amount'),{'id':'sql-model','name':'SQL模型','type':'SQL','content':'SELECT category,amount AS value FROM sales'}]}
            await catalog.initialize(db,api,refresh)
            models=await catalog.models()
            assert [f['columnId'] for f in next(m for m in models if m['modelCode']=='sales-model')['schemaList']]==['category']
            assert next(f for f in next(m for m in models if m['modelCode']=='sql-model')['schemaList'] if f['columnId']=='value')['dataType']=='DECIMAL'
            failed={**cfg,'forceRefresh':True,'modelList':[dict(cfg['modelList'][0],content='table_does_not_exist')]}
            with pytest.raises(Exception):await catalog.initialize(db,api,failed)
            assert await catalog.models()==models
            # Restore the intended configuration so independent browser/replays remain reproducible.
            await catalog.initialize(db,api,{**cfg,'forceRefresh':True})
        finally:
            await db.close();await ledger.close()


def test_closure_conversation_upload_real_input_archive_and_cross_visitor(env,client):
    import io,zipfile
    raw='category,amount\n中文A,0.10\nB,0.20\n'.encode()
    r=client.post('/api/agent/file/upload',data={'sessionId':'closure-input'},files={'file':('input.csv',raw,'text/csv')})
    assert r.status_code==200,r.text
    dto=r.json();assert dto['resourceKey'].startswith('closure-input:input.csv:')
    assert client.get(dto['previewUrl']).content==raw
    archive=client.get('/api/agent/workspace/closure-input/archive')
    assert archive.status_code==200
    with zipfile.ZipFile(io.BytesIO(archive.content)) as z:assert z.read('input/input.csv')==raw
    with other(env) as b:
        assert b.get('/api/agent/workspace/closure-input/archive').status_code==403
        assert b.post('/api/agent/file/upload',data={'sessionId':'closure-input'},files={'file':('input.csv',b'overwrite','text/csv')}).status_code==403
    assert client.get(dto['downloadUrl']).content==raw
