"""Isolated protocol tests; production auth always verifies real persisted identity."""
import time
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'reactor-tool'))
from types import SimpleNamespace
import httpx
import pytest
from reactor_backend.adapters.private_resources import PrivateResources,ResourceDenied


def resources():
    api=SimpleNamespace(settings=SimpleNamespace(tool_service_token='test-only-service-token-32-characters'),headers={'X-Reactor-Service-Token':'test-only-service-token-32-characters'})
    return PrivateResources(None,api)


def test_signed_scope_rejects_tampering_expiry_and_plain_headers(monkeypatch):
    r=resources();scope=r.scope_headers('visitor-a','session-a')['X-Reactor-Analysis-Scope']
    assert r.verify_scope(scope)['visitor']=='visitor-a'
    with pytest.raises(ResourceDenied):r.verify_scope(scope[:-1]+('0' if scope[-1]!='0' else '1'))
    with pytest.raises(ResourceDenied):r.verify_scope('visitor-a')
    now=time.time();monkeypatch.setattr(time,'time',lambda:now+1201)
    with pytest.raises(ResourceDenied):r.verify_scope(scope)


async def test_original_internal_middleware_context_reset_and_host_scoped_headers(monkeypatch):
    from reactor_tool.util.internal_auth import InternalServiceAuth,analysis_scope,file_headers
    token='test-only-service-token-32-characters'
    monkeypatch.setenv('REACTOR_TOOL_AUTH_REQUIRED','true');monkeypatch.setenv('REACTOR_TOOL_SERVICE_TOKEN',token)
    monkeypatch.setenv('FILE_SERVER_URL','http://protected.test/v1/file_tool')
    async def app(scope,receive,send):
        from starlette.responses import JSONResponse
        await JSONResponse({'scope':analysis_scope.get(),'external_headers':file_headers('https://external.test/source'),'internal_authenticated':bool(file_headers('http://protected.test/v1/file_tool/preview/x/y'))})(scope,receive,send)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=InternalServiceAuth(app)),base_url='http://tool.test') as c:
        assert (await c.get('/v1/tool/anything')).status_code==403
        assert (await c.get('/v1/tool/anything',headers={'X-Reactor-Service-Token':'wrong'})).status_code==403
        result=(await c.get('/v1/tool/anything',headers={'X-Reactor-Service-Token':token,'X-Reactor-Analysis-Scope':'test-signed-context'})).json()
        assert result=={'scope':'test-signed-context','external_headers':{},'internal_authenticated':True}
        assert analysis_scope.get()==''
        assert (await c.get('/v1/tool/anything',headers={'X-Reactor-Service-Token':token})).json()['scope']==''


async def test_metadata_index_real_adapter_request_contract_and_failure():
    from reactor_backend.adapters.data_catalog import DataCatalog
    calls=[]
    def upstream(request):
        import json
        calls.append((request.method,str(request.url),json.loads(request.content) if request.content and not request.url.path.endswith('_bulk') else None))
        if request.url.path=='/collections/reactor_model_schema' and request.method=='GET':return httpx.Response(404)
        if request.url.path=='/v1/tool/embedding/text':return httpx.Response(200,json={'vectors':[[1,0,0]]})
        return httpx.Response(200,json={})
    schema={'columnId':'amount','columnName':'金额','synonyms':None,'columnComment':None,'fewShot':'0.10','dataType':'DECIMAL','vectorUuid':'1,2,3,4','modelCode':'sales-model'}
    planned=[({'id':'sales-model','type':'TABLE','content':'sales'},[schema])]
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as http:
        api=SimpleNamespace(client=http,base_url='http://original-tool.test',headers={})
        catalog=DataCatalog(None)
        await catalog.sync_indexes(None,api,{'qdrant':{'enable':True,'url':'http://qdrant.test'}},planned)
        vectors=next(data['points'] for method,url,data in calls if url.endswith('/points?wait=true'))
        assert len(vectors)==1 and vectors[0]['payload']==schema
        assert any(method=='PUT' and url.endswith('/collections/reactor_model_schema') and data['vectors']['size']==3 for method,url,data in calls)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(503))) as http:
        api.client=http
        with pytest.raises(httpx.HTTPStatusError):await catalog.sync_indexes(None,api,{'qdrant':{'enable':True,'url':'http://qdrant.test'}},planned)


async def test_es_sync_with_real_sqlite_values_and_explicit_bulk_failure(tmp_path):
    import sqlite3,json
    from reactor_backend.adapters.business_db import BusinessDB
    from reactor_backend.adapters.data_catalog import DataCatalog
    path=tmp_path/'business.sqlite'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE source(category TEXT)');c.executemany('INSERT INTO source VALUES (?)',[('中文',),('中文',),('B',)])
    calls=[];fail=False
    def upstream(request):
        calls.append((request.method,request.url.path,request.content))
        if request.method=='HEAD':return httpx.Response(404)
        return httpx.Response(200,json={'errors':fail} if request.url.path=='/_bulk' else {})
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        api=SimpleNamespace(client=client,base_url='http://original-tool.test',headers={})
        db=BusinessDB({'type':'sqlite','path':str(path)},client)
        catalog=DataCatalog(None);schema={'columnId':'category','modelCode':'source','dataType':'VARCHAR'}
        planned=[({'id':'source','type':'TABLE','content':'source','syncValueFields':'category'},[schema])]
        try:
            await catalog.sync_indexes(db,api,{'es':{'enable':True,'url':'http://es.test'}},planned)
            bulk=next(raw for method,path,raw in calls if path=='/_bulk')
            docs=[json.loads(line) for line in bulk.decode().splitlines()][1::2]
            assert {d['value'] for d in docs}=={'中文','B'}
            assert any(path.endswith('/_delete_by_query') for method,path,raw in calls)
            fail=True
            with pytest.raises(ValueError,match='sync failed'):await catalog.sync_indexes(db,api,{'es':{'enable':True,'url':'http://es.test'}},planned)
        finally:await db.close()
