"""Original DataAgent HTTP/ChatDataMessage protocol; never Agent SSE frames."""
import asyncio
import logging
from fastapi import Request
from fastapi.responses import JSONResponse,Response,StreamingResponse
from reactor_backend.models.types import encode

log=logging.getLogger(__name__)


def install_data(app,service):
    async def body(request):
        try:
            data=await request.json()
            if not isinstance(data,dict):raise ValueError()
            return data
        except (ValueError,TypeError):return None
    async def respond(fn):
        try:return JSONResponse(await fn())
        except Exception as exc:
            log.exception('Data query failed (%s)',type(exc).__name__)
            return JSONResponse({'message':str(exc) if isinstance(exc,ValueError) else type(exc).__name__},status_code=500)
    async def authorize(request):
        if getattr(app.state,'private_identity',None):
            visitor,scope=await app.state.private_identity(request)
            return visitor
        return None
    @app.middleware('http')
    async def protect_data(request,call_next):
        if request.url.path.startswith('/data/'):
            from reactor_backend.adapters.private_resources import ResourceDenied
            try:request.state.resource_visitor=await authorize(request)
            except ResourceDenied as exc:return JSONResponse({'detail':str(exc)},status_code=403)
        return await call_next(request)
    @app.post('/data/queryModelInfo')
    async def model_info(request:Request):
        if await body(request) is None:return Response(status_code=400)
        return await respond(lambda:service.prepare('',recall=False))
    @app.get('/data/allModels')
    async def all_models():
        async def result():return {'code':200,'data':await service.catalog.models()}
        return await respond(result)
    @app.get('/data/previewData')
    async def preview_data(modelCode:str):
        async def result():return {'code':200,'data':await service.preview(modelCode)}
        return await respond(result)
    @app.post('/data/getNl2SqlReq')
    async def nlreq(request:Request):
        data=await body(request)
        if data is None:return Response(status_code=400)
        return await respond(lambda:service.prepare(data.get('content') or ''))
    @app.post('/data/testQuery')
    async def test_query(request:Request):
        data=await body(request)
        if data is None:return Response(status_code=400)
        return await respond(lambda:service.db.query(data.get('content') or ''))
    @app.post('/data/apiChatQuery')
    async def api_query(request:Request):
        data=await body(request)
        if data is None:return Response(status_code=400)
        # Original API returns [] on execution failure, with an explicit server error log.
        try:
            _,result,_=await service.query(data.get('content'),data.get('traceId'),visitor=getattr(request.state,'resource_visitor',None));return JSONResponse(result)
        except Exception as exc:
            log.exception('apiChatQuery failed: %s',type(exc).__name__);return JSONResponse([])
    @app.post('/data/chatQuery')
    async def chat_query(request:Request):
        data=await body(request)
        if data is None:return Response(status_code=400)
        queue=asyncio.Queue()
        async def emit(kind,value):await queue.put({'eventType':kind,'data':value})
        async def work():
            try:
                _,result,_=await service.query(data.get('content'),data.get('traceId'),emit,visitor=getattr(request.state,'resource_visitor',None))
                await emit('CHART_DATA',result)
            except Exception as exc:
                log.exception('chatQuery failed: %s',type(exc).__name__)
                await emit('ERROR',str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
            finally:
                await emit('READY','');await queue.put(None)
        task=asyncio.create_task(work());app.state.data_tasks.add(task)
        task.add_done_callback(app.state.data_tasks.discard)
        async def stream():
            while True:
                event=await queue.get()
                if event is None:break
                yield ('data:'+encode(event)+'\n\n').encode()
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    @app.post('/data/vectorRecall')
    async def vector(request:Request):
        data=await body(request)
        if data is None:return Response(status_code=400)
        return await respond(lambda:service.vector(data))
    @app.post('/data/esRecall')
    async def elastic(request:Request):
        data=await body(request)
        if data is None:return Response(status_code=400)
        return await respond(lambda:service.elastic(data))

