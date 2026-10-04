import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from reactor_backend.application.query import normalize
from reactor_backend.projection.events import wire, control, frame
from reactor_backend.projection.history import session_view, history_view

METHODS = ["GET","POST","PUT","PATCH","DELETE","OPTIONS","HEAD"]


def envelope(data=None,code="0000",info="成功"):
    return {"code":code,"info":info,"data":data}


def profile(visitor):
    return {"visitorId":visitor["visitor_id"],"username":visitor.get("username"),"named":bool((visitor.get("username") or "").strip())}


def install(app: FastAPI, ledger, runs, settings):

    async def identity(request):
        forwarded = request.headers.get("x-forwarded-for","").split(",")[0].strip()
        visitor, token = await ledger.identity(request.cookies.get(settings.cookie_name),
                        forwarded or (request.client.host if request.client else None),request.headers.get("user-agent"))
        return visitor, token

    def cookie(response, token):
        if token:
            response.set_cookie(settings.cookie_name, token, max_age=365*24*3600,
                                httponly=True,secure=settings.cookie_secure,samesite="lax",path="/")
        return response

    async def body(request):
        try:
            data = await request.json()
            if not isinstance(data,dict): raise ValueError()
            return data
        except (ValueError,TypeError):
            return None

    async def stream_frames(stream, queue):
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(),settings.heartbeat_seconds)
                except TimeoutError:
                    yield wire(control(stream.query.request_id,"heartbeat"))
                    continue
                if event is None:
                    break
                yield wire(event)
        finally:
            stream.observers.discard(queue)  # Only detach this observer, never cancel its owner.

    def one_frame(payload):
        async def single(): yield wire(payload)
        return StreamingResponse(single(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

    @app.api_route("/web/health",methods=METHODS)
    async def health():
        return Response("ok",media_type="text/event-stream")

    @app.get("/api/agent/visitor/bootstrap")
    async def bootstrap(request: Request):
        visitor, token = await identity(request)
        return cookie(JSONResponse(envelope(profile(visitor))),token)

    @app.get("/api/v1/admin/ai-client-model/query-enabled")
    async def enabled_models():
        # Original workbench selector consumes metadata, never API secrets.
        from fastapi.encoders import jsonable_encoder
        return JSONResponse(envelope(jsonable_encoder(await ledger.enabled_model_metadata())))

    @app.post("/api/agent/visitor/naming")
    async def naming(request: Request):
        data = await body(request)
        if data is None: return Response(status_code=400)
        if data.get("username") is not None:
            if not isinstance(data["username"],(str,int,float,bool)): return Response(status_code=400)
            if not isinstance(data["username"],str): data["username"] = str(data["username"]).lower() if isinstance(data["username"],bool) else str(data["username"])
        visitor, token = await identity(request)
        try:
            result = envelope(profile(await ledger.name_visitor(visitor["visitor_id"],data.get("username"))))
        except ValueError as exc:
            result = envelope(code="0002",info=str(exc))
        return cookie(JSONResponse(result),token)

    @app.api_route("/web/api/v1/gpt/queryAgentStreamIncr",methods=METHODS)
    @app.api_route("/1/web/api/v1/gpt/queryAgentStreamIncr",methods=METHODS)
    async def query(request: Request):
        data = await body(request)
        if data is None: return Response(status_code=400)
        # Match Jackson typed fields; reject bad DTO binding before touching persistence.
        for key in ("query","sessionId","requestId","traceId","user","model","thinkingEffort","outputStyle"):
            if key in data and data[key] is not None and not isinstance(data[key], (str,int,float,bool)):
                return Response(status_code=400)
            if key in data and data[key] is not None and not isinstance(data[key],str):
                data[key] = str(data[key]).lower() if isinstance(data[key],bool) else str(data[key])
        if "deepThink" in data and data["deepThink"] is not None:
            try:
                if isinstance(data["deepThink"],bool): raise ValueError()
                data["deepThink"] = int(data["deepThink"])
            except (ValueError,TypeError): return Response(status_code=400)
        for key in ("thinking","forcePlanMode"):
            if key in data and data[key] is not None and not isinstance(data[key],bool):
                if str(data[key]).lower() not in ("true","false"): return Response(status_code=400)
                data[key] = str(data[key]).lower() == "true"
        if data.get("sessionFiles") is not None and not isinstance(data["sessionFiles"],list):
            return Response(status_code=400)
        visitor, token = await identity(request)
        q = normalize(data,visitor["visitor_id"])
        try:
            if getattr(app.state,'check_private_file_url',None):
                for file in q.session_files or []:
                    for field in ('url','previewUrl','downloadUrl','domainUrl','ossUrl'):
                        if file.get(field):await app.state.check_private_file_url(q.visitor_id,file[field])
            await ledger.owner(q.visitor_id,q.session_id,q.query,True)
            if getattr(app.state,'private_resources',None):await app.state.private_resources.namespace(q.visitor_id,q.session_id)
            if await ledger.has_open_interaction(q.session_id):
                raise ValueError("当前会话有待处理的交互请求")
            stream = runs.start(q)
            queue = stream.attach()
            response = StreamingResponse(stream_frames(stream,queue),media_type="text/event-stream",
                                         headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
        except ValueError as exc:
            response = one_frame(frame(q.request_id,"failed",True,errorMsg=str(exc),packageType="result"))
        return cookie(response,token)

    @app.get("/api/agent/conversation/sessions")
    async def sessions(request: Request):
        try: limit = int(request.query_params.get("limit","20"))
        except ValueError: return Response(status_code=400)
        visitor, token = await identity(request)
        data = [session_view(s) for s in await ledger.recent(visitor["visitor_id"],limit)]
        return cookie(JSONResponse(envelope(data)),token)

    @app.get("/api/agent/conversation/sessions/{session_id}")
    async def detail(session_id: str, request: Request):
        visitor, token = await identity(request)
        try:
            session, facts = await ledger.history(visitor["visitor_id"],session_id)
            result = envelope(history_view(session,facts,settings.context_window))
        except ValueError as exc:
            result = envelope(code="0001",info=str(exc))
        return cookie(JSONResponse(result),token)

    @app.post("/api/agent/run/follow")
    async def follow(request: Request):
        data = await body(request)
        if data is None: return Response(status_code=400)
        visitor, token = await identity(request)
        request_id = str(data.get("requestId") or "").strip()
        try: cursor = int(data.get("lastEventSeq") or 0)
        except (ValueError,TypeError): return Response(status_code=400)
        from reactor_backend.transport.control import follow_response
        response = await follow_response(ledger,runs,settings,visitor["visitor_id"],request_id,data.get("sessionId"),cursor,stream_frames)
        return cookie(response,token)

    from reactor_backend.transport.control import install_control
    install_control(app,ledger,runs,settings,identity,cookie,body,stream_frames,envelope)
