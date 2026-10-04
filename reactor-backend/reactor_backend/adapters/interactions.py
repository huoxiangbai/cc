"""Durable two-phase interactions on the original tables. No in-memory CAS substitute."""
import json
from uuid import uuid4
from sqlalchemy import text

KINDS = {'question': ('user_question','question_id','questions_json','answers_json'),
         'approval': ('plan_approval','approval_id','plan_content','decision_json')}
OPEN = ('PENDING','RESUME_PENDING','RESUMING')
DENIED = '无权访问该资源'


def decoded(value, default=None):
    return json.loads(value) if isinstance(value,str) else value if value is not None else default


def spec(kind):
    if kind not in KINDS:
        raise ValueError('Unknown interaction kind')
    table, key, content, decision = KINDS[kind]
    return 'ai_agent_'+table, key, content, decision


def client_payload(kind, r):
    _,key,content,decision = spec(kind)
    status = r['status']
    payload = {'messageType':'ask_user_question' if kind == 'question' else 'plan_approval',
               'questionId' if kind == 'question' else 'approvalId': r[key],
               'sessionId': r['session_id'], 'requestId':r['source_request_id'],
               'toolCallId':r.get('tool_call_id'), 'resumeRequestId':r.get('resume_request_id'),
               'persistenceStatus':status,
               'status':('answered' if kind == 'question' else 'decided') if status in ('RESUME_PENDING','RESUMING','ANSWERED') else
                        'timeout' if status == 'TIMEOUT' else 'cancelled' if status in ('CANCELLED','FAILED') else 'pending'}
    if r.get('expires_at'):
        payload['expiresAt'] = r['expires_at'].isoformat()
    if kind == 'question':
        payload['questions'] = decoded(r[content],[])
        if r.get(decision) is not None:
            payload['answers'] = decoded(r[decision],{})
    else:
        payload.update(planContent=r[content],planFilePath=r.get('plan_file_path'))
        payload.update(decoded(r.get(decision),{}))
    return payload


def observation(kind, r, waiting=False):
    if kind == 'question':
        value = dict(tool='AskUserQuestion',ok=True,questionId=r['question_id'],questions=decoded(r['questions_json'],[]),
                     message='Waiting for user to answer AskUserQuestion.' if waiting else 'User has answered your questions. Continue with the answers in mind.')
        if not waiting:
            value['answers'] = decoded(r.get('answers_json'),{})
    else:
        d = decoded(r.get('decision_json'),{})
        value = dict(tool='ExitPlanMode',ok=True,approvalId=r['approval_id'])
        if waiting:
            value.update(plan=r['plan_content'],message='Waiting for user to approve ExitPlanMode plan.')
        elif d.get('approved'):
            ctx = decoded(r.get('resume_context_json'),{})
            restored = (ctx.get('planMode') or {}).get('prePlanMode') or 'default'
            value.update(approved=True,plan=d.get('editedPlanContent') or r['plan_content'],filePath=r.get('plan_file_path'),
                         restoredMode=restored,message='User approved the plan. Continue executing the approved plan.')
        else:
            value.update(approved=False,stillInPlanMode=True,feedback=d.get('feedback'),message='User rejected the plan. Stay in plan mode, revise using feedback, and request approval again.')
    if waiting:
        value['status'] = 'waiting_user_input'
    return value


class InteractionStore:
    # Imported lazily to avoid adapters/mysql import cycles.
    @staticmethod
    def authorize(c, visitor, session):
        from reactor_backend.adapters.mysql import rows
        if not visitor or not session:
            raise ValueError(DENIED)
        s = rows(c,'SELECT visitor_id FROM ai_agent_dialogue_session WHERE session_id=:s AND deleted=0',s=session)
        if not s or s[0]['visitor_id'] != visitor:
            raise ValueError(DENIED)

    async def create_interaction(self, kind, query, run, call, tool_id, content, context, path=None):
        from reactor_backend.adapters.mysql import rows
        from reactor_backend.models.types import encode
        table,key,column,_ = spec(kind)
        uid = ('q_' if kind == 'question' else 'approval_') + uuid4().hex
        def work(c):
            self.authorize(c,query.visitor_id,query.session_id)
            values = {key:uid,'visitor_id':query.visitor_id,'session_id':query.session_id,
                      'source_run_id':run['id'],'source_request_id':query.request_id,
                      'tool_invocation_id':tool_id,'tool_call_id':call.id,column:encode(content) if kind == 'question' else content,
                      'resume_context_json':encode(context)}
            c.execute(text('SELECT NOW(3)'))
            values['expires_at'] = c.execute(text('SELECT DATE_ADD(NOW(3), INTERVAL 30 MINUTE)')).scalar()
            if kind == 'approval':
                values['plan_file_path'] = path
            cols=','.join(values); args=','.join(':'+x for x in values)
            c.execute(text(f'INSERT INTO {table}({cols}) VALUES({args})'),values)
            return rows(c,f'SELECT * FROM {table} WHERE {key}=:uid AND deleted=0',uid=uid)[0]
        return await self.transact(work)

    async def interaction(self, kind, visitor, uid=None, resume=None):
        from reactor_backend.adapters.mysql import rows
        table,key,_,_=spec(kind)
        def work(c):
            rs=rows(c,f'SELECT * FROM {table} WHERE {key if uid else "resume_request_id"}=:uid AND deleted=0',uid=uid or resume)
            if not rs:
                return None
            self.authorize(c,visitor,rs[0]['session_id'])
            if not visitor or rs[0]['visitor_id'] != visitor:
                raise ValueError(DENIED)
            return rs[0]
        return await self.transact(work)

    async def pending_interactions(self, kind, visitor, session):
        from reactor_backend.adapters.mysql import rows
        table,_,_,_=spec(kind)
        def work(c):
            self.authorize(c,visitor,session)
            c.execute(text(f"UPDATE {table} SET status='TIMEOUT' WHERE session_id=:s AND visitor_id=:v AND status='PENDING' AND expires_at<=NOW(3) AND deleted=0"),{'s':session,'v':visitor})
            # Closed cards are returned too, so refresh restores cancellation/expiry/decision.
            return rows(c,f'SELECT * FROM {table} WHERE session_id=:s AND visitor_id=:v AND deleted=0 ORDER BY create_time,id',s=session,v=visitor)
        return [client_payload(kind,r) for r in await self.transact(work)]

    async def decide_interaction(self, kind, visitor, uid, decision):
        from reactor_backend.adapters.mysql import rows
        from reactor_backend.models.types import encode
        table,key,_,column=spec(kind)
        client_key='questionId' if kind == 'question' else 'approvalId'
        def work(c):
            rs=rows(c,f'SELECT * FROM {table} WHERE {key}=:uid AND deleted=0 FOR UPDATE',uid=uid)
            if not rs:
                return {client_key:uid,'accepted':False,'message':'问题不存在' if kind == 'question' else '审批不存在'}
            r=rs[0]
            self.authorize(c,visitor,r['session_id'])
            if not visitor or r['visitor_id'] != visitor:
                raise ValueError(DENIED)
            resume='resume_'+uuid4().hex
            changed=c.execute(text(f"UPDATE {table} SET status='RESUME_PENDING',{column}=:d,resume_request_id=:resume WHERE id=:id AND visitor_id=:v AND status='PENDING' AND deleted=0 AND (expires_at IS NULL OR expires_at>NOW(3))"),{'d':encode(decision),'resume':resume,'id':r['id'],'v':visitor}).rowcount
            if not changed:
                c.execute(text(f"UPDATE {table} SET status='TIMEOUT' WHERE id=:id AND status='PENDING' AND deleted=0 AND expires_at<=NOW(3)"),{'id':r['id']})
            r=rows(c,f'SELECT * FROM {table} WHERE id=:id',id=r['id'])[0]
            accepted=r['status'] in ('RESUME_PENDING','RESUMING','ANSWERED')
            result={client_key:uid,'accepted':accepted,'idempotent':accepted and not bool(changed),
                    'status':r['status'],'sessionId':r['session_id'],
                    'message':'请求已过期' if r['status']=='TIMEOUT' else '请连接 resume SSE 继续' if accepted else '请求已结束'}
            if accepted:
                result['resumeRequestId']=r['resume_request_id']
            if kind == 'approval' and accepted:
                result['decision']='approved' if decoded(r['decision_json'],{}).get('approved') else 'rejected'
            return result
        return await self.transact(work)

    async def claim_interaction(self, kind, visitor, resume):
        from reactor_backend.adapters.mysql import rows
        table,_,_,_=spec(kind)
        def work(c):
            rs=rows(c,f'SELECT * FROM {table} WHERE resume_request_id=:resume AND deleted=0',resume=resume)
            if not rs:
                return None,False
            r=rs[0]
            self.authorize(c,visitor,r['session_id'])
            if not visitor or r['visitor_id'] != visitor:
                raise ValueError(DENIED)
            count=c.execute(text(f"UPDATE {table} SET status='RESUMING' WHERE id=:id AND visitor_id=:v AND status='RESUME_PENDING' AND resume_request_id=:resume AND deleted=0"),{'id':r['id'],'v':visitor,'resume':resume}).rowcount
            # Under MySQL REPEATABLE READ a plain reread can retain the pre-claim snapshot.
            # Locking read observes the winner's committed state after the conditional UPDATE.
            r=rows(c,f'SELECT * FROM {table} WHERE id=:id FOR UPDATE',id=r['id'])[0]
            return r,bool(count)
        return await self.transact(work)

    async def settle_interaction(self, kind, resume, target, release=False):
        table,_,_,_=spec(kind)
        if target not in ('ANSWERED','FAILED','RESUME_PENDING') or (target=='RESUME_PENDING') != release:
            raise ValueError('Invalid interaction settlement')
        # Release is legal only when no RunB exists. Unknown dispatch never returns the claim.
        extra=" AND NOT EXISTS (SELECT 1 FROM ai_agent_dialogue_run r WHERE r.request_id=:resume AND r.deleted=0)" if release else ''
        return await self.transact(lambda c:c.execute(text(f"UPDATE {table} SET status=:target WHERE resume_request_id=:resume AND status='RESUMING' AND deleted=0"+extra),{'resume':resume,'target':target}).rowcount)

    async def cancel_interaction(self, kind, visitor, uid):
        r=await self.interaction(kind,visitor,uid=uid)
        if not r:
            return False
        table,_,_,_=spec(kind)
        return bool(await self.transact(lambda c:c.execute(text(f"UPDATE {table} SET status='CANCELLED' WHERE id=:id AND visitor_id=:v AND status IN ('PENDING','RESUME_PENDING') AND deleted=0"),{'id':r['id'],'v':visitor}).rowcount))

    async def stop_interactions(self, visitor, request_id, session):
        from reactor_backend.adapters.mysql import rows
        def work(c):
            self.authorize(c,visitor,session)
            count=0; resumes=[]
            for kind in KINDS:
                table,_,_,_=spec(kind)
                rs=rows(c,f"SELECT resume_request_id FROM {table} WHERE visitor_id=:v AND session_id=:s AND (source_request_id=:r OR resume_request_id=:r) AND status='RESUMING' AND deleted=0",v=visitor,s=session,r=request_id)
                resumes.extend(r['resume_request_id'] for r in rs)
                count+=c.execute(text(f"UPDATE {table} SET status='CANCELLED' WHERE visitor_id=:v AND session_id=:s AND (source_request_id=:r OR resume_request_id=:r) AND status IN ('PENDING','RESUME_PENDING') AND deleted=0"),{'v':visitor,'s':session,'r':request_id}).rowcount
            return count,resumes
        return await self.transact(work)
