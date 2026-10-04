"""Original GenUI, image workbench and featured HTTP contracts."""
import asyncio
import secrets
from datetime import datetime
from fastapi import Request
from fastapi.responses import Response,JSONResponse
from fastapi.encoders import jsonable_encoder
from reactor_backend.models.types import Query
from reactor_backend.transport.http import envelope
from reactor_backend.adapters.featured import Featured
from reactor_backend.adapters.private_resources import ResourceDenied
from reactor_backend.delivery import genui_export


def install_delivery(app,ledger,runs,settings):
    featured=Featured(ledger);app.state.featured=featured
    async def export(request,format):
        try:
            body=await request.json()
            if not isinstance(body,dict):return Response(status_code=400)
            output=await asyncio.to_thread(getattr(genui_export,format),body.get('tree'),body.get('mode','document'))
            kind='application/pdf' if format=='pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            return Response(output,media_type=kind,headers={'Content-Disposition':f'attachment; filename="genui-{datetime.now():%Y%m%d-%H%M%S}.{format}"'})
        except ValueError as exc:return JSONResponse({'code':'400','info':str(exc)},status_code=400)
        except Exception as exc:return JSONResponse({'code':'500','info':str(exc)},status_code=500)
    @app.post('/api/agent/genui/export/pdf')
    async def pdf(request:Request):return await export(request,'pdf')
    @app.post('/api/agent/genui/export/docx')
    async def docx(request:Request):return await export(request,'docx')
    @app.post('/api/agent/image-generation/generate')
    async def generate(request:Request):
        visitor,_=await app.state.private_identity(request)
        try:
            body=await request.json()
            if not isinstance(body,dict):raise ValueError('请求体不能为空')
            rid=body.get('requestId') or secrets.token_hex(16)
            if not isinstance(rid,str) or len(rid)>64:raise ValueError('无效 requestId')
            existing=await ledger.transact(lambda c:__import__('reactor_backend.adapters.mysql',fromlist=['rows']).rows(c,'SELECT id FROM ai_agent_tool_output_image_generation WHERE request_id=:id',id=rid))
            if existing:raise ValueError('requestId 对应批次已存在')
            resources=app.state.private_resources
            await resources.namespace(visitor,rid);await resources.claim_new(visitor,'image_batch',rid)
            query=Query(rid,rid,visitor,None,rid,'user',0)
            result=await runs.runtime.images.workspace(body,query)
            return JSONResponse(envelope(jsonable_encoder(result)))
        except ResourceDenied:raise
        except ValueError as exc:return JSONResponse(envelope(code='0002',info=str(exc)))
        except Exception as exc:return JSONResponse(envelope(code='0001',info=str(exc)))
    @app.get('/api/agent/image-generation/history')
    async def history(request:Request,pageNo:int=1,pageSize:int=10):
        visitor,_=await app.state.private_identity(request)
        return JSONResponse(envelope(await runs.runtime.images.history(visitor,pageNo,pageSize)))
    @app.get('/api/agent/featured-conversations/home')
    async def home(limit:int=6):return JSONResponse(envelope((await featured.listing(size=limit))['list']))
    @app.get('/api/agent/featured-conversations')
    async def listing(pageNo:int=1,pageSize:int=20):return JSONResponse(envelope(await featured.listing(pageNo,pageSize)))
    @app.get('/api/agent/featured-conversations/{featuredId}')
    async def detail(featuredId:str):return JSONResponse(envelope(await featured.detail(featuredId)))
    async def admin(request,operation):
        try:
            data=await request.json() if operation in ('create','update','query-list') else {'featuredId':request.path_params['featuredId']}
            if not isinstance(data,dict):return Response(status_code=400)
            if operation=='query-list':result=await featured.listing(data.get('pageNo',1),data.get('pageSize',20),data,True)
            else:result=await featured.mutate(operation,data,request.state.admin['username'])
            return JSONResponse(envelope(result))
        except ValueError as exc:return JSONResponse(envelope(code='0002',info=str(exc)))
    for method,path,operation in [('POST','create','create'),('PUT','update','update'),('POST','query-list','query-list'),('POST','online/{featuredId}','online'),('POST','offline/{featuredId}','offline')]:
        def factory(op):
            async def route(request:Request):return await admin(request,op)
            return route
        app.add_api_route('/api/v1/admin/featured-conversations/'+path,factory(operation),methods=[method])
