"""Exact original HTTP-only admin routes, protected by approved P0 authentication."""
import asyncio
import json
import time
from importlib.resources import files
from urllib.parse import urlsplit
from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse,Response
from reactor_backend.adapters.admin_store import AdminStore,SPECS
from reactor_backend.transport.http import envelope

COOKIE='reactor_admin_token'
PUBLIC={'/api/v1/admin/admin-user/login','/api/v1/admin/admin-user/validate-login','/api/v1/admin/ai-client-model/query-enabled'}

def csrf(request,settings):
    if request.method in ('GET','HEAD','OPTIONS'):return True
    if request.headers.get('sec-fetch-site')=='cross-site':return False
    origin=request.headers.get('origin')
    own=str(request.base_url).rstrip('/')
    return origin is None or origin==own or origin in settings.cors_origins


def install_admin(app,ledger,runs,settings,client):
    store=AdminStore(ledger);app.state.admin_store=store
    skill_lock=asyncio.Lock()
    from reactor_backend.skills.registry import Registry
    skills=Registry(settings.skill_root)

    @app.middleware('http')
    async def authenticate(request,call_next):
        if request.url.path.startswith('/api/v1/admin/') and request.method!='OPTIONS':
            if not csrf(request,settings):return JSONResponse(envelope(code='0003',info='跨站请求被拒绝'))
            if request.url.path not in PUBLIC:
                admin=await store.authenticate(request.cookies.get(COOKIE))
                if not admin:return JSONResponse(envelope(code='0003',info='需要管理员登录'))
                request.state.admin=admin
        return await call_next(request)

    @app.post('/api/v1/admin/admin-user/logout')
    async def logout(request:Request):
        await store.logout(request.cookies.get(COOKIE));r=JSONResponse(envelope(True));r.delete_cookie(COOKIE,path='/');return r

    async def invoke(request,kind,operation):
        data={}
        if request.method in ('POST','PUT') and operation not in ('reload',) and not operation.startswith('test') and operation not in ('upload','parse-package'):
            try:data=await request.json()
            except ValueError:return Response(status_code=400)
            if not isinstance(data,dict):return Response(status_code=400)
        params=request.path_params
        if kind=='admin-user' and operation in ('login','validate-login'):
            if any(data.get(k) is not None and not isinstance(data[k],str) for k in ('username','password')):return Response(status_code=400)
            if operation=='validate-login':
                if not (data.get('username') or '').strip() or not (data.get('password') or '').strip():return JSONResponse(envelope(False,'0002','用户名或密码不能为空'))
                valid=await store.credentials(data['username'],data['password'])
                return JSONResponse(envelope(bool(valid),'0000' if valid else '0003','成功' if valid else '登录失败'))
            admin,token=await store.login(data.get('username'),data.get('password'))
            if not admin:return JSONResponse(envelope(code='0002',info='用户名或密码错误'))
            r=JSONResponse(envelope(jsonable_encoder(admin)));r.set_cookie(COOKIE,token,max_age=8*3600,httponly=True,secure=settings.cookie_secure,samesite='lax',path='/');return r
        try:
            if kind=='skills':
                async with skill_lock:
                    # P4 registry is real, OS-owned, and never exposed through a visitor tool.
                    if operation=='list':result=await asyncio.to_thread(skills.list)
                    elif operation in ('upload','parse-package'):
                        form=await request.form();upload=form.get('file')
                        if not upload or not hasattr(upload,'read'):return Response(status_code=400)
                        payload=await upload.read(32*1024*1024+1)
                        if operation=='parse-package':result=await asyncio.to_thread(skills.preview,payload)
                        else:result=await asyncio.to_thread(skills.install,payload,str(request.query_params.get('replace',form.get('replace','false'))).lower()=='true')
                    elif operation=='create':result=await asyncio.to_thread(skills.create,data)
                    elif operation=='import-url':result=await skills.import_url(client,data.get('url',''),data.get('replace') is True)
                    elif operation=='reload':await asyncio.to_thread(skills.reload);result=True
                    else:result=await asyncio.to_thread(skills.delete,params['name'])
            elif kind=='sub-agent-definitions':
                if operation=='tool-catalog':
                    result=json.loads(files('reactor_backend').joinpath('resources/subagent_tool_catalog.json').read_text())
                elif operation=='reload':result=sum(r['status']==1 for r in await store.subagents())
                elif operation=='query-list':result=await store.subagents()
                elif request.method=='GET':
                    result=await store.subagents(params['agentKey'])
                    if result is None:return JSONResponse(envelope(code='0002',info='agentKey 不存在'))
                else:
                    if request.method=='DELETE':data={'agentKey':params.get('agentKey') or request.query_params.get('agentKey')};operation='delete'
                    result=await store.subagent_write(operation,data)
            elif operation.startswith('test'):
                ref='__db_binding__:'+str(params['id']) if operation=='test-by-id' else params['modelId']
                from reactor_backend.models.types import Query
                start=time.monotonic()
                try:
                    q=Query('admin-test','admin-test',request.state.admin['userId'],'ping','admin-test','user',0,model=ref)
                    await runs.runtime.model.complete([{'role':'user','content':'ping'}],[],q)
                    result=dict(ok=True,ms=int((time.monotonic()-start)*1000),message='连接成功')
                except Exception:
                    # Provider exception strings can contain URLs/credentials; do not disclose them.
                    result=dict(ok=False,ms=0,message='连接失败: 模型调用失败')
            elif operation.startswith('query'):
                value=next(iter(params.values()),None)
                if params and next(iter(params)) in ('id','status'):
                    try:value=int(value)
                    except ValueError:return Response(status_code=400)
                result=await store.query(kind,operation,value,data)
                if result is None and kind in ('ai-client-api','ai-client-model'):return JSONResponse(envelope(code='0001',info='未找到对应的AI客户端'+('API' if kind=='ai-client-api' else '模型')+'配置'))
            else:
                _,_,fields=SPECS[kind]
                for key in ('id','status','supportsThinking','contextWindow','requestTimeout'):
                    if data.get(key) is not None:
                        try:
                            if isinstance(data[key],bool):raise ValueError()
                            data[key]=int(data[key])
                        except (ValueError,TypeError):return Response(status_code=400)
                value=next(iter(params.values()),None)
                if params and next(iter(params))=='id':
                    try:value=int(value)
                    except ValueError:return Response(status_code=400)
                result=await store.mutate(kind,operation,data,value)
                # Model/MCP/SubAgent runtime reads enabled definitions per request: no stale cache.
            return JSONResponse(envelope(jsonable_encoder(result)))
        except ValueError as exc:
            if kind=='skills':return JSONResponse(envelope(code='0001',info=str(exc)))
            return JSONResponse(envelope(False if request.method!='GET' else None,code='0002',info=str(exc)))
        except Exception:
            return JSONResponse(envelope(False if request.method in ('POST','PUT','DELETE') and kind in SPECS else None,code='0001',info='未知失败'))

    manifest=json.loads(files('reactor_backend').joinpath('resources/admin_routes.json').read_text())
    # Literal routes precede variable routes (/delete must not become an agentKey).
    for item in sorted(manifest,key=lambda i:'{' in i['path']):
        parts=item['path'].split('/');kind=parts[4];operation=parts[5]
        def endpoint_for(kind,operation):
            async def endpoint(request:Request):return await invoke(request,kind,operation)
            return endpoint
        app.add_api_route(item['path'],endpoint_for(kind,operation),methods=[item['method']],name=kind+'-'+operation)
