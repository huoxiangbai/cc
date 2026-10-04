"""P2 actual MySQL races, TCP stream control and original schema persistence."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
import time
from uuid import uuid4
import httpx
import pytest
from sqlalchemy import text
from reactor_backend.adapters.mysql import MySQLLedger
from reactor_backend.adapters.recovery import recover
from reactor_backend.models.types import Query,ToolCall,ToolReply
from test_integration import env,client


def frames(response):return [json.loads(l[5:]) for l in response.text.splitlines() if l.startswith('data:')]

def send(c,s,r,q,deep=0):
    response=c.post('/web/api/v1/gpt/queryAgentStreamIncr',json=dict(sessionId=s,requestId=r,query=q,deepThink=deep))
    assert response.status_code==200
    return frames(response)

def payload(frame):return frame['resultMap']['eventData']['resultMap']

def pending(c,kind,s):
    response=c.get('/api/agent/'+kind+'/pending',params=dict(sessionId=s))
    assert response.json()['code']=='0000'
    return response.json()['data']

def await_status(env,request,status):
    for _ in range(200):
        with env[3].connect() as c:
            result=c.execute(text('SELECT status FROM ai_agent_dialogue_run WHERE request_id=:r'),dict(r=request)).scalar()
        if result==status:return
        time.sleep(.01)
    pytest.fail('Expected run terminal status '+str(status))


def test_11_question_answer_resume_duplicate_owner_and_file(env,client):
    events=send(client,'session-ask-p2','request-ask-p2','P2_ASK')
    card=payload(events[-1])['resultMap']
    assert card['messageType']=='ask_user_question' and card['persistenceStatus']=='PENDING'
    assert events[-1]['finished']
    await_status(env,'request-ask-p2',5)
    question=card['questionId'];answer=dict(questionId=question,answers={'方向':'研究'})
    first=client.post('/api/agent/ask-user/answer',json=answer).json()['data']
    again=client.post('/api/agent/ask-user/answer',json=answer).json()['data']
    assert first['accepted'] and not first['idempotent'] and again['idempotent'] and first['resumeRequestId']==again['resumeRequestId']
    with httpx.Client(base_url=env[1],trust_env=False) as other:
        assert other.post('/api/agent/ask-user/answer',json=answer).json()['code']=='0001'
        assert other.get('/api/agent/ask-user/pending',params=dict(sessionId='session-ask-p2')).json()['code']=='0001'
        denied=frames(other.post('/api/agent/ask-user/resume',json=dict(resumeRequestId=first['resumeRequestId'])))
        assert denied[-1]['errorMsg']=='无权访问该资源'
    resumed=frames(client.post('/api/agent/ask-user/resume',json=dict(resumeRequestId=first['resumeRequestId'])))
    assert resumed[-1]['status']=='success' and resumed[-1]['finished']
    assert '按用户回答' in payload(resumed[-1])['result']
    duplicate=client.post('/api/agent/ask-user/resume',json=dict(resumeRequestId=first['resumeRequestId']))
    assert 'follow_idle' in duplicate.text
    with env[3].connect() as c:
        r=c.execute(text('SELECT * FROM ai_agent_user_question WHERE question_id=:q'),dict(q=question)).mappings().one()
        assert r['status']=='ANSWERED' and r['source_run_id'] and r['tool_invocation_id']
        assert c.execute(text('SELECT COUNT(*) FROM ai_agent_dialogue_run WHERE request_id=:r'),dict(r=first['resumeRequestId'])).scalar()==1
        assert c.execute(text("SELECT llm_oberserve FROM ai_agent_tool_invocation WHERE id=:t"),dict(t=r['tool_invocation_id'])).scalar().find('answers')>=0
    assert (env[0]/'workspace/session-ask-p2/回答报告.md').read_text().find('研究')>=0
    assert pending(client,'ask-user','session-ask-p2')[0]['status']=='answered'


def test_12_plan_reject_revise_edit_approve_and_refresh(env,client):
    events=send(client,'session-plan-p2','request-plan-p2','P2_PLAN',1)
    a=payload(events[-1])['resultMap'];assert a['messageType']=='plan_approval'
    assert client.get('/api/agent/conversation/sessions/session-plan-p2').json()['data']['status']=='WAITING_INPUT'
    restored=pending(client,'plan-approval','session-plan-p2')[0]
    assert restored['approvalId']==a['approvalId'] and restored['planContent'].startswith('# P2')
    rejection=client.post('/api/agent/plan-approval/reject',json=dict(approvalId=a['approvalId'],feedback='增加证据')).json()['data']
    revised=frames(client.post('/api/agent/plan-approval/resume',json=dict(resumeRequestId=rejection['resumeRequestId'])))
    b=payload(revised[-1])['resultMap'];assert b['approvalId']!=a['approvalId'] and '增加证据' in b['planContent']
    edited='# 用户编辑后的计划\n生成真实报告'
    decision=client.post('/api/agent/plan-approval/approve',json=dict(approvalId=b['approvalId'],editedPlanContent=edited)).json()['data']
    done=frames(client.post('/api/agent/plan-approval/resume',json=dict(resumeRequestId=decision['resumeRequestId'])))
    assert done[-1]['status']=='success' and '批准或编辑' in payload(done[-1])['result']
    assert (env[0]/'workspace/session-plan-p2/.reactor/plan.md').read_text()==edited
    assert (env[0]/'workspace/session-plan-p2/计划报告.md').read_text()==edited
    assert all(r['persistenceStatus']=='ANSWERED' for r in pending(client,'plan-approval','session-plan-p2'))
    history=client.get('/api/agent/conversation/sessions/session-plan-p2').json()['data']
    assert history['deepThink'] and len(history['runs'])==3


@pytest.mark.parametrize('kind',['question','approval'])
async def test_13_mysql_concurrent_decide_and_claim_only_one(env,client,kind):
    ledger=MySQLLedger(os.environ['P1_TEST_MYSQL_URL'])
    visitor=client.get('/api/agent/visitor/bootstrap').json()['data']['visitorId']
    uid=uuid4().hex[:12]
    q=Query('race-source-'+uid,'race-session-'+uid,visitor,'CAS fixture','trace','reactor',5)
    try:
        run=await ledger.start_run(q)
        llm=await ledger.start_llm(run['id'],1,1,'fixed',[],[])
        call=ToolCall('race-call-'+uid,'AskUserQuestion' if kind=='question' else 'ExitPlanMode','{}')
        tool=await ledger.start_tool(run['id'],llm,call,0,1,{})
        row=await ledger.create_interaction(kind,q,run,call,tool,[] if kind=='question' else 'race plan',{'agentType':5})
        await ledger.finish_run(run,5,'',None,[])
        key='question_id' if kind=='question' else 'approval_id'
        results=await asyncio.gather(*(ledger.decide_interaction(kind,visitor,row[key],{'方向':'研究'} if kind=='question' else {'approved':True}) for _ in range(24)))
        assert sum(not r['idempotent'] for r in results)==1 and len({r['resumeRequestId'] for r in results})==1
        resume=results[0]['resumeRequestId']
        claims=await asyncio.gather(*(ledger.claim_interaction(kind,visitor,resume) for _ in range(24)))
        assert sum(won for _,won in claims)==1
        assert all(record['status']=='RESUMING' for record,_ in claims)
        assert await ledger.settle_interaction(kind,resume,'RESUME_PENDING',release=True)==1
        assert (await ledger.claim_interaction(kind,visitor,resume))[1]
        assert await ledger.settle_interaction(kind,resume,'ANSWERED')==1
        assert await ledger.settle_interaction(kind,resume,'FAILED')==0
        assert (await ledger.interaction(kind,visitor,resume=resume))['status']=='ANSWERED'
    finally:await ledger.close()


def test_14_tcp_root_returns_child_drains_reconnect_and_single_visitor(env,client):
    with client.stream('POST','/web/api/v1/gpt/queryAgentStreamIncr',json=dict(sessionId='session-bg-p2',requestId='request-bg-p2',query='P2_BG bgfile')) as response:
        seen=[]
        for line in response.iter_lines():
            if not line.startswith('data:'):continue
            f=json.loads(line[5:]);seen.append(f)
            if f.get('resultMap') and payload(f)['messageType']=='result':
                assert not f['finished'] and not payload(f)['finish'];cursor=f['eventSeq'];break
    # Root is durable SUCCESS while active ownership persists through background drain.
    blocked=send(client,'session-bg-other','request-bg-other','P2_DIRECT')
    assert blocked[-1]['status']=='failed' and '访客' in blocked[-1]['errorMsg']
    with httpx.Client(base_url=env[1],trust_env=False,timeout=30) as other:
        assert send(other,'session-other-visitor','request-other-visitor','P2_DIRECT')[-1]['status']=='success'
        for route in ('stop','inject','follow'):
            data=dict(requestId='request-bg-p2',text='attack')
            r=other.post('/api/agent/run/'+route,json=data)
            if route=='follow':assert frames(r)[-1]['errorMsg']=='无权访问该资源'
            else:assert r.json()['code']=='0001'
    followed=frames(client.post('/api/agent/run/follow',json=dict(requestId='request-bg-p2',sessionId='session-bg-p2',lastEventSeq=cursor)))
    assert all(f['eventSeq']>cursor for f in followed if f['eventSeq'])
    assert payload(followed[-1])['messageType']=='stream_settle' and followed[-1]['finished']
    assert (env[0]/'workspace/session-bg-p2/worker-bgfile.md').is_file()
    with env[3].connect() as c:
        run=c.execute(text("SELECT * FROM ai_agent_dialogue_run WHERE request_id='request-bg-p2'")).mappings().one()
        child=c.execute(text('SELECT * FROM ai_agent_tool_invocation WHERE run_id=:r AND sub_agent_id IS NOT NULL'),dict(r=run['id'])).mappings().one()
        parent=c.execute(text('SELECT * FROM ai_agent_tool_invocation WHERE run_id=:r AND tool_name=\'Agent\''),dict(r=run['id'])).mappings().one()
        assert child['parent_tool_call_id']==parent['tool_call_id'] and child['sub_agent_id']
        assert json.loads(parent['llm_oberserve'])['status']=='completed'
        scopes=c.execute(text('SELECT DISTINCT memory_scope FROM ai_agent_working_memory_turn WHERE session_id=:s'),dict(s=run['session_id'])).scalars().all()
        assert 'main' in scopes and len(scopes)==2
        assert run['tool_call_count']==2


def test_15_real_sync_child_and_mailbox_consumption(env,client):
    assert send(client,'session-sync-p2','request-sync-p2','P2_SYNC syncfile')[-1]['status']=='success'
    assert send(client,'session-mail-p2','request-mail-p2','P2_MAIL mailfile')[-1]['status']=='success'
    with env[3].connect() as c:
        for s in ('session-sync-p2','session-mail-p2'):
            assert c.execute(text('SELECT status FROM ai_agent_background_task WHERE session_id=:s'),dict(s=s)).scalar()=='completed'
        assert '收到指导' in c.execute(text("SELECT output FROM ai_agent_background_task WHERE session_id='session-mail-p2'")).scalar()


def test_16_waiting_stop_cancel_expiry_and_late_terminal(env,client):
    s='session-wait-stop-p2';events=send(client,s,'request-wait-stop-p2','P2_ASK');question=payload(events[-1])['resultMap']['questionId']
    first=client.post('/api/agent/run/stop',json=dict(requestId='request-wait-stop-p2')).json()['data']
    again=client.post('/api/agent/run/stop',json=dict(requestId='request-wait-stop-p2')).json()['data']
    assert first['stopped'] and first['firstCancel'] and not again['firstCancel']
    assert pending(client,'ask-user',s)[0]['persistenceStatus']=='CANCELLED'
    assert client.post('/api/agent/ask-user/answer',json=dict(questionId=question,answers={})).json()['data']['accepted'] is False
    assert client.get('/api/agent/conversation/sessions/'+s).json()['data']['status']=='WAITING_INPUT'
    events=send(client,'session-expiry-p2','request-expiry-p2','P2_ASK');question=payload(events[-1])['resultMap']['questionId']
    with env[3].begin() as c:c.execute(text("UPDATE ai_agent_user_question SET expires_at=DATE_SUB(NOW(3),INTERVAL 1 SECOND) WHERE question_id=:q"),dict(q=question))
    expired=client.post('/api/agent/ask-user/answer',json=dict(questionId=question,answers={})).json()
    assert expired['code']=='0000' and expired['data']['accepted'] is False and expired['data']['message']=='请求已过期'
    assert pending(client,'ask-user','session-expiry-p2')[0]['status']=='timeout'


def test_17_tcp_stop_and_inject_before_next_step(env,client):
    with client.stream('POST','/web/api/v1/gpt/queryAgentStreamIncr',json=dict(sessionId='session-stop-p2',requestId='request-stop-p2',query='P2_STOP')) as r:
        for line in r.iter_lines():
            if line.startswith('data:') and payload(json.loads(line[5:]))['messageType']=='tool_result':break
        assert client.post('/api/agent/run/inject',json=dict(requestId='request-stop-p2',text='用户控制面指导')).json()['data']['accepted']
        assert client.post('/api/agent/run/stop',json=dict(requestId='request-stop-p2')).json()['data']['stopped']
    await_status(env,'request-stop-p2',4)
    with env[3].connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM ai_agent_session_todo WHERE session_id='session-stop-p2'")).scalar()==1
        assert c.execute(text("SELECT COUNT(*) FROM ai_agent_dialogue_run WHERE request_id='request-stop-p2'")).scalar()==1
    assert 'follow_idle' in client.post('/api/agent/run/follow',json=dict(requestId='request-stop-p2')).text


def test_18_todo_mysql_dependencies_and_capability_owner(env,client):
    assert send(client,'session-todo-p2','request-todo-p2','P2_TODO')[-1]['status']=='success'
    with env[3].connect() as c:
        todos=c.execute(text("SELECT * FROM ai_agent_session_todo WHERE session_id='session-todo-p2' ORDER BY seq_no")).mappings().all()
        assert len(todos)==2 and todos[1]['status']=='in_progress' and json.loads(todos[1]['blocked_by_json'])==['1']
    for kind in ('skill','mcp'):
        assert client.put('/api/agent/session/session-todo-p2/capabilities',json=dict(kind=kind,refId='isolated-ref',enabled=False)).json()['data'] is True
    with httpx.Client(base_url=env[1],trust_env=False) as other:
        for method in ('get','put'):
            kwargs={'json':dict(kind='skill',refId='isolated-ref',enabled=True)} if method=='put' else {}
            assert getattr(other,method)('/api/agent/session/session-todo-p2/capabilities',**kwargs).json()['code']=='0001'
    with env[3].connect() as c:
        assert c.execute(text("SELECT SUM(enabled) FROM ai_agent_session_capability WHERE session_id='session-todo-p2'")).scalar()==0


async def test_19_resume_admission_rejection_releases_claim_and_terminal_cas(env,client):
    events=send(client,'session-reject-claim-p2','request-reject-claim-p2','P2_ASK');qid=payload(events[-1])['resultMap']['questionId']
    decision=client.post('/api/agent/ask-user/answer',json=dict(questionId=qid,answers={'方向':'分析'})).json()['data']
    with client.stream('POST','/web/api/v1/gpt/queryAgentStreamIncr',json=dict(sessionId='session-busy-p2',requestId='request-busy-p2',query='P2_STOP')) as busy:
        for line in busy.iter_lines():
            if line.startswith('data:'):break
        refused=frames(client.post('/api/agent/ask-user/resume',json=dict(resumeRequestId=decision['resumeRequestId'])))
        assert refused[-1]['status']=='failed' and '访客' in refused[-1]['errorMsg']
        with env[3].connect() as c:
            assert c.execute(text('SELECT status FROM ai_agent_user_question WHERE question_id=:q'),dict(q=qid)).scalar()=='RESUME_PENDING'
            assert c.execute(text('SELECT COUNT(*) FROM ai_agent_dialogue_run WHERE request_id=:r'),dict(r=decision['resumeRequestId'])).scalar()==0
        client.post('/api/agent/run/stop',json=dict(requestId='request-busy-p2'))
    await_status(env,'request-busy-p2',4)
    assert frames(client.post('/api/agent/ask-user/resume',json=dict(resumeRequestId=decision['resumeRequestId'])))[-1]['status']=='success'
    ledger=MySQLLedger(os.environ['P1_TEST_MYSQL_URL'])
    try:
        r=(await ledger.find_run(decision['resumeRequestId']))[0]
        assert await ledger.finish_run(r,2,'late failure','late',[])==1
        assert await ledger.settle_interaction('question',r['request_id'],'FAILED')==0
        assert await ledger.settle_interaction('question',r['request_id'],'RESUME_PENDING',release=True)==0
    finally:await ledger.close()


async def test_20_tcp_follow_park_pending_idle_and_owner(env,client):
    ledger=MySQLLedger(os.environ['P1_TEST_MYSQL_URL'])
    visitor=client.get('/api/agent/visitor/bootstrap').json()['data']['visitorId']
    q=Query('park-request-p2','park-session-p2',visitor,'follow race fixture','trace','reactor',5)
    try:
        run=await ledger.start_run(q)  # committed before dispatch; no side effects are executed
        with httpx.Client(base_url=env[1],trust_env=False,timeout=20) as other:
            denied=frames(other.post('/api/agent/run/follow',json=dict(requestId=q.request_id)))
            assert denied[-1]['errorMsg']=='无权访问该资源'
        denied=frames(client.post('/api/agent/run/follow',json=dict(requestId=q.request_id,sessionId='wrong-session')))
        assert denied[-1]['errorMsg']=='无权访问该资源'
        response=frames(client.post('/api/agent/run/follow',json=dict(requestId=q.request_id,lastEventSeq=9)))
        assert len(response)==1 and response[0]['packageType']=='follow_pending' and response[0]['retryMs']==800 and not response[0]['finished']
        await ledger.finish_run(run,1,'fixture settled',None,[])
        assert frames(client.post('/api/agent/run/follow',json=dict(requestId=q.request_id)))[0]['packageType']=='follow_idle'
        assert frames(client.post('/api/agent/run/follow',json=dict(requestId='no-such-p2-run')))[0]['packageType']=='follow_idle'
    finally:await ledger.close()


def test_21_model_catalog_original_ui_metadata_no_secrets(env,client):
    columns=('id','modelId','apiId','modelName','modelType','modelUsage','supportsThinking','contextWindow','status','createTime','updateTime')
    with env[3].begin() as c:
        c.execute(text("INSERT INTO ai_client_model(model_id,api_id,model_name,model_type,model_usage,supports_thinking,context_window,status) VALUES('p2-catalog-only','p2-no-api','catalog-model','openai','fallback',1,32000,1)"))
    records=client.get('/api/v1/admin/ai-client-model/query-enabled').json()
    assert records['code']=='0000'
    r=next(r for r in records['data'] if r['modelId']=='p2-catalog-only')
    assert set(r)==set(columns) and r['supportsThinking']==1 and r['contextWindow']==32000 and r['modelUsage']=='fallback'
    assert 'apiKey' not in r and 'baseUrl' not in r


def test_22_legacy_empty_owner_cannot_be_claimed_by_query_or_history(env,client):
    with env[3].begin() as c:
        c.execute(text("INSERT INTO ai_agent_dialogue_session(session_id,visitor_id,title) VALUES('legacy-unowned-p2',NULL,'legacy')"))
    rejected=send(client,'legacy-unowned-p2','claim-legacy-p2','P2_DIRECT')
    assert rejected[-1]['errorMsg']=='无权访问该资源'
    assert client.get('/api/agent/conversation/sessions/legacy-unowned-p2').json()['code']=='0001'
    with env[3].connect() as c:
        assert c.execute(text("SELECT visitor_id FROM ai_agent_dialogue_session WHERE session_id='legacy-unowned-p2'")).scalar() is None
        assert c.execute(text("SELECT COUNT(*) FROM ai_agent_dialogue_run WHERE request_id='claim-legacy-p2'")).scalar()==0


def test_23_concurrent_tcp_resume_dispatches_one_run_and_one_tool_effect(env,client):
    s='tcp-resume-race-p2'
    event=send(client,s,'tcp-resume-source-p2','P2_ASK')[-1]
    qid=payload(event)['resultMap']['questionId']
    decision=client.post('/api/agent/ask-user/answer',json=dict(questionId=qid,answers={'方向':'研究'})).json()['data']
    def resume(_):
        with httpx.Client(base_url=env[1],cookies=client.cookies,trust_env=False,timeout=30) as c:
            r=c.post('/api/agent/ask-user/resume',json=dict(resumeRequestId=decision['resumeRequestId']))
            assert r.status_code==200
            return frames(r)
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(resume,range(12)))
    await_status(env,decision['resumeRequestId'],1)
    with env[3].connect() as c:
        assert c.execute(text('SELECT COUNT(*) FROM ai_agent_dialogue_run WHERE request_id=:r'),dict(r=decision['resumeRequestId'])).scalar()==1
        assert c.execute(text("SELECT COUNT(*) FROM ai_agent_tool_invocation t JOIN ai_agent_dialogue_run r ON r.id=t.run_id WHERE r.request_id=:r AND t.tool_name='text_processor'"),dict(r=decision['resumeRequestId'])).scalar()==1
        assert c.execute(text('SELECT status FROM ai_agent_user_question WHERE question_id=:q'),dict(q=qid)).scalar()=='ANSWERED'
    assert (env[0]/'workspace'/s/'回答报告.md').is_file()
    assert all(not any(f.get('status')=='failed' for f in result) for result in results),[[f.get('errorMsg') for f in result if f.get('status')=='failed'] for result in results]
