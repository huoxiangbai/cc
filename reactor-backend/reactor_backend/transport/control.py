"""Control and HITL HTTP boundaries; resource ownership is checked before any mutation."""
import asyncio
from dataclasses import replace
from pathlib import Path
import re
from fastapi import Request
from fastapi.responses import JSONResponse,Response,StreamingResponse
from reactor_backend.adapters.interactions import DENIED,decoded
from reactor_backend.models.types import Query
from reactor_backend.projection.events import frame,control,wire

HEADERS={'Cache-Control':'no-cache','X-Accel-Buffering':'no'}


def one_frame(payload):
    async def single():yield wire(payload)
    return StreamingResponse(single(),media_type='text/event-stream',headers=HEADERS)


def denied_stream(request_id):
    return one_frame(frame(request_id,'failed',True,errorMsg=DENIED,packageType='result'))


async def authorized_run(ledger,runs,visitor,request_id,session=None):
    active=runs.active.get(request_id)
    if active:
        if not visitor or active.query.visitor_id!=visitor or session and active.query.session_id!=session:raise ValueError(DENIED)
        await ledger.transact(lambda c:ledger.authorize(c,visitor,active.query.session_id))
        return active.query.session_id
    found=await ledger.find_run(request_id)
    if not found:return None
    r=found[0]
    if not visitor or r['visitor_id']!=visitor or session and r['session_id']!=session:raise ValueError(DENIED)
    await ledger.transact(lambda c:ledger.authorize(c,visitor,r['session_id']))
    return r['session_id']


async def follow_response(ledger,runs,settings,visitor,request_id,session,cursor,stream_frames,expected_pending=False):
    if not request_id:return one_frame(control('', 'follow_idle',True))
    try:await authorized_run(ledger,runs,visitor,request_id,session)
    except ValueError:return denied_stream(request_id)
    stream=runs.active.get(request_id)
    if stream:return StreamingResponse(stream_frames(stream,stream.attach(cursor)),media_type='text/event-stream',headers=HEADERS)
    found=await ledger.find_run(request_id)
    if (not found and not expected_pending) or found and found[0]['status']!=0:return one_frame(control(request_id,'follow_idle',True))
    async def park():
        for _ in range(50):
            await asyncio.sleep(.2)
            active=runs.active.get(request_id)
            if active:
                if active.query.visitor_id!=visitor:
                    yield wire(frame(request_id,'failed',True,errorMsg=DENIED,packageType='result'));return
                async for chunk in stream_frames(active,active.attach(cursor)):yield chunk
                return
            rs=await ledger.find_run(request_id)
            if not rs and not expected_pending or rs and rs[0]['status']!=0:
                yield wire(control(request_id,'follow_idle',True));return
        yield wire(control(request_id,'follow_pending',retryMs=800))
    return StreamingResponse(park(),media_type='text/event-stream',headers=HEADERS)


def install_control(app,ledger,runs,settings,identity,cookie,body,stream_frames,envelope):
    @app.post('/api/agent/run/stop')
    async def stop(request:Request):
        data=await body(request)
        if data is None:return Response(status_code=400)
        visitor,token=await identity(request)
        request_id=str(data.get('requestId') or '').strip();session=data.get('sessionId')
        if not request_id:return cookie(JSONResponse(envelope(code='0002',info='requestId 不能为空')),token)
        try:
            sid=await authorized_run(ledger,runs,visitor['visitor_id'],request_id,session)
            stopped,first=runs.stop(request_id)
            cancelled=0
            if sid:
                cancelled,resumes=await ledger.stop_interactions(visitor['visitor_id'],request_id,sid)
                for resume in resumes:
                    found=await ledger.find_run(resume)
                    s,f=runs.stop(resume,pending=not found)
                    stopped=stopped or s;first=first or f
            result=dict(requestId=request_id,sessionId=session,stopped=stopped or bool(cancelled),firstCancel=first or bool(cancelled),
                        message='已请求停止' if stopped or cancelled else '未找到进行中的 run（可能已结束）')
            response=JSONResponse(envelope(result))
        except ValueError as exc:response=JSONResponse(envelope(code='0001',info=DENIED if str(exc)==DENIED else str(exc)))
        return cookie(response,token)

    @app.post('/api/agent/run/inject')
    async def inject(request:Request):
        data=await body(request)
        if data is None:return Response(status_code=400)
        visitor,token=await identity(request)
        request_id=str(data.get('requestId') or '').strip();session=data.get('sessionId');text=str(data.get('text') or '').strip()
        if not request_id or not text:return cookie(JSONResponse(envelope(code='0002',info='requestId/text 不能为空')),token)
        try:
            await authorized_run(ledger,runs,visitor['visitor_id'],request_id,session)
            accepted=runs.inject(request_id,text)
            result=dict(requestId=request_id,sessionId=session,accepted=accepted,message='已接受指导，将在下一步生效' if accepted else '未找到进行中的 run（可能已结束）')
            if accepted:
                result['queued']=True
                stream=runs.active[request_id]
                stream.control.injections[-1]['notified']=True
                await stream.control.emit('user_inject','inject:'+str(stream.control.llm_seq)+':queued:'+str(len(stream.control.injections)),{'resultMap':{'text':text[:8000],'source':'user','status':'queued'}})
            response=JSONResponse(envelope(result,code='0000' if accepted else '0001',info='成功' if accepted else result['message']))
        except ValueError:response=JSONResponse(envelope(code='0001',info=DENIED))
        return cookie(response,token)

    def register(kind,prefix,key):
        async def decision(request:Request):
            data=await body(request)
            if data is None:return Response(status_code=400)
            visitor,token=await identity(request)
            uid=str(data.get(key) or '').strip()
            if not uid:return cookie(JSONResponse(envelope(code='0002',info=key+' 不能为空')),token)
            if kind=='question':
                d=data.get('answers') or {}
                if not isinstance(d,dict) or any(not isinstance(v,str) for v in d.values()):return Response(status_code=400)
            else:
                d=dict(approved=request.url.path.endswith('/approve'),feedback=data.get('feedback'),editedPlanContent=data.get('editedPlanContent') if request.url.path.endswith('/approve') else None)
                if any(v is not None and not isinstance(v,str) for k,v in d.items() if k!='approved'):return Response(status_code=400)
            try:response=JSONResponse(envelope(await ledger.decide_interaction(kind,visitor['visitor_id'],uid,d)))
            except ValueError:response=JSONResponse(envelope(code='0001',info=DENIED))
            return cookie(response,token)
        async def pending(request:Request):
            visitor,token=await identity(request)
            session=request.query_params.get('sessionId')
            try:response=JSONResponse(envelope(await ledger.pending_interactions(kind,visitor['visitor_id'],session)))
            except ValueError:response=JSONResponse(envelope(code='0001',info=DENIED))
            return cookie(response,token)
        async def cancel(request:Request):
            data=await body(request)
            if data is None:return Response(status_code=400)
            visitor,token=await identity(request)
            uid=str(data.get(key) or '').strip()
            if not uid:return cookie(JSONResponse(envelope(code='0002',info=key+' 不能为空')),token)
            try:response=JSONResponse(envelope({key:uid,'cancelled':await ledger.cancel_interaction(kind,visitor['visitor_id'],uid),'reason':'user_cancelled'}))
            except ValueError:response=JSONResponse(envelope(code='0001',info=DENIED))
            return cookie(response,token)
        async def resume(request:Request):
            data=await body(request)
            if data is None:return Response(status_code=400)
            visitor,token=await identity(request)
            resume_id=str(data.get('resumeRequestId') or '').strip()
            if not resume_id:return cookie(one_frame(frame('', 'failed',True,errorMsg='resumeRequestId 不能为空',packageType='result')),token)
            try:
                record,claimed=await ledger.claim_interaction(kind,visitor['visitor_id'],resume_id)
                if not record:response=one_frame(frame(resume_id,'failed',True,errorMsg='恢复请求不存在',packageType='result'))
                elif not claimed:
                    # Duplicate claim observes the existing execution or its terminal fact.
                    if record['status'] in ('RESUMING','ANSWERED'):
                        response=await follow_response(ledger,runs,settings,visitor['visitor_id'],resume_id,record['session_id'],0,stream_frames,expected_pending=record['status']=='RESUMING')
                    else:response=one_frame(frame(resume_id,'failed',True,errorMsg='恢复请求已结束',packageType='result'))
                else:
                    ctx=decoded(record.get('resume_context_json'),{})
                    record['_kind']=kind
                    q=Query(resume_id,record['session_id'],visitor['visitor_id'],'',resume_id,'reactor',ctx.get('agentType') or (3 if ctx.get('entryAgent')=='plan_solve' else 5),
                            model=ctx.get('model'),thinking=ctx.get('thinking'),thinking_effort=ctx.get('thinkingEffort'),resume=record)
                    try:stream=runs.start(q)
                    except ValueError as exc:
                        await ledger.settle_interaction(kind,resume_id,'RESUME_PENDING',release=True)
                        response=one_frame(frame(resume_id,'failed',True,errorMsg=str(exc),packageType='result'))
                    else:response=StreamingResponse(stream_frames(stream,stream.attach()),media_type='text/event-stream',headers=HEADERS)
            except ValueError:response=denied_stream(resume_id)
            return cookie(response,token)
        for suffix in ('answer',) if kind=='question' else ('approve','reject'):
            app.add_api_route(prefix+'/'+suffix,decision,methods=['POST'])
        app.add_api_route(prefix+'/pending',pending,methods=['GET'])
        app.add_api_route(prefix+'/cancel',cancel,methods=['POST'])
        app.add_api_route(prefix+'/resume',resume,methods=['POST'])
    register('question','/api/agent/ask-user','questionId')
    register('approval','/api/agent/plan-approval','approvalId')

    @app.api_route('/api/agent/session/{session_id}/capabilities',methods=['GET','PUT'])
    async def capabilities(session_id:str,request:Request):
        visitor,token=await identity(request)
        toggle=await body(request) if request.method=='PUT' else None
        if request.method=='PUT' and toggle is None:return Response(status_code=400)
        try:
            differences=await ledger.capabilities(visitor['visitor_id'],session_id,toggle)
            if toggle is not None:result=True
            else:
                overrides={(r['kind'],r['ref_id']):bool(r['enabled']) for r in differences}
                skills=[]
                if settings.skill_root:
                    from reactor_backend.skills.registry import Registry,SkillScope
                    from reactor_backend.runtime.workspace import Workspace
                    registry=await asyncio.to_thread(Registry,settings.skill_root)
                    scope=SkillScope(registry,Workspace(settings.workspace_root,session_id),())
                    for entry in await asyncio.to_thread(scope.list):
                        name=entry['name']
                        skills.append(dict(refId=name,name=name,enabled=overrides.get(('skill',name),True),source=entry.get('source','system')))
                mcps=[dict(refId=r['refId'],name=r['name'],enabled=overrides.get(('mcp',r['refId']),True),source='platform') for r in await ledger.mcp_capabilities()]
                result=dict(locked=False,skills=skills,mcpServers=mcps)
            response=JSONResponse(envelope(result))
        except ValueError as exc:response=JSONResponse(envelope(code='0001',info=str(exc)))
        return cookie(response,token)
