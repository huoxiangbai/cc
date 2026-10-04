"""Actual kill/restart on a second NEW database inside the harness' isolated MySQL."""
import asyncio
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from uuid import uuid4
import httpx
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from reactor_backend.adapters.mysql import MySQLLedger
from test_integration import env
from test_p2_integration import frames,payload

ROOT=Path(__file__).resolve().parents[2]


def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


async def test_actual_process_restart_no_side_effect_replay_claim_orphan_and_success_settlement(env):
    isolation=env[0]/'restart';isolation.mkdir()
    name='reactor_p2_restart_'+uuid4().hex[:8]
    with env[3].begin() as c:c.execute(text('CREATE DATABASE '+name+' CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'))
    url=make_url(os.environ['P1_TEST_MYSQL_URL']).set(database=name)
    engine=create_engine(url,hide_parameters=True)
    with engine.begin() as c:
        for statement in re.findall(r'CREATE TABLE IF NOT EXISTS.*?ENGINE=.*?;', (ROOT/'Reactor-agent-app/src/main/resources/db/schema.sql').read_text(),re.S):c.execute(text(statement))
        acl=(ROOT/'reactor-backend/migrations/001_private_resource_acl.sql').read_text().split('CREATE TABLE',1)[1]
        c.execute(text('CREATE TABLE'+acl))
        for name in ('002_admin_session.sql','003_featured_resource.sql'):
            c.execute(text((ROOT/'reactor-backend/reactor_backend/resources/migrations'/name).read_text()))
    backend_port=port();base=f'http://127.0.0.1:{backend_port}'
    base_env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','TMPDIR')}
    base_env.update(PYTHONPATH=str(ROOT/'reactor-backend'),REACTOR_MYSQL_URL=url.render_as_string(hide_password=False),
                    REACTOR_TOOL_SERVICE_TOKEN=os.environ['P1_TEST_SERVICE_TOKEN'],REACTOR_TOOL_URL=env[2],REACTOR_WORKSPACE_ROOT=str(isolation/'workspace'),REACTOR_COOKIE_SECURE='false',
                    REACTOR_MODEL_BASE_URL=os.environ['P1_TEST_MODEL_URL'],REACTOR_MODEL_NAME='p2-fixed-upstream',REACTOR_MODEL_API_KEY='isolation-test-key',
                    REACTOR_BACKEND_PORT=str(backend_port),REACTOR_RECOVER_EXCLUSIVE='true')
    processes=[];logs=[]
    def start():
        log=(isolation/('backend-'+str(len(processes))+'.log')).open('w');logs.append(log)
        p=subprocess.Popen([sys.executable,'-m','reactor_backend'],cwd=isolation,env=base_env,stdout=log,stderr=subprocess.STDOUT);processes.append(p)
        for _ in range(200):
            if p.poll() is not None:raise RuntimeError('Isolated restart backend exited; inspect '+str(isolation))
            try:
                if httpx.get(base+'/web/health',trust_env=False,timeout=.2).status_code==200:return p
            except httpx.HTTPError:pass
            time.sleep(.02)
        raise RuntimeError('Restart readiness timeout')
    ledger=MySQLLedger(url.render_as_string(hide_password=False))
    try:
        backend=start()
        with httpx.Client(base_url=base,trust_env=False,timeout=30) as client:
            v=client.get('/api/agent/visitor/bootstrap').json()['data']['visitorId']
            acl_upload=client.post('/api/agent/file/upload',data={'sessionId':'restart-acl'},files={'file':('acl.txt',b'persistent owner','text/plain')})
            assert acl_upload.status_code==200,acl_upload.text
            from urllib.parse import urlsplit
            acl_path=urlsplit(acl_upload.json()['previewUrl']).path
            assert client.get(acl_path).text=='persistent owner'
            kb=None
            if env[0].name.startswith('reactor-p3-'):
                kb=client.post('/v1/documents/create_knowledge_base',json={'kb_name':'重启权限库'}).json()['data']['kb_id']
            res=client.post('/web/api/v1/gpt/queryAgentStreamIncr',json=dict(sessionId='restart-ask',requestId='restart-ask-a',query='P2_ASK'))
            question=payload(frames(res)[-1])['resultMap']['questionId']
            decided=client.post('/api/agent/ask-user/answer',json=dict(questionId=question,answers={'方向':'研究'})).json()['data']
            record,won=await ledger.claim_interaction('question',v,decided['resumeRequestId']);assert won
            # claim-before-dispatch: no RunB exists, so restart must FAIL instead of replaying.
            with client.stream('POST','/web/api/v1/gpt/queryAgentStreamIncr',json=dict(sessionId='restart-effects',requestId='restart-effects-a',query='P2_STOP')) as response:
                for line in response.iter_lines():
                    if line.startswith('data:') and payload(json.loads(line[5:]))['messageType']=='tool_result':break
                # Todo side effect is committed and the following LLM invocation is in flight.
                for _ in range(100):
                    with engine.connect() as c:
                        n=c.execute(text("SELECT COUNT(*) FROM ai_agent_llm_invocation l JOIN ai_agent_dialogue_run r ON r.id=l.run_id WHERE r.request_id='restart-effects-a' AND l.status=0")).scalar()
                    if n:break
                    time.sleep(.01)
                assert n
                # A different visitor's root can finish while its child is still running.
                with httpx.Client(base_url=base,trust_env=False,timeout=30) as other:
                    with other.stream('POST','/web/api/v1/gpt/queryAgentStreamIncr',json=dict(sessionId='restart-bg',requestId='restart-bg-a',query='P2_BG restartbg')) as bg:
                        for line in bg.iter_lines():
                            if line.startswith('data:') and payload(json.loads(line[5:]))['messageType']=='result':break
                    with engine.connect() as c:
                        assert c.execute(text("SELECT status FROM ai_agent_dialogue_run WHERE request_id='restart-bg-a'")).scalar()==1
                        assert c.execute(text("SELECT status FROM ai_agent_background_task WHERE session_id='restart-bg'")).scalar()=='running'
                for _ in range(100):
                    captured=httpx.get(os.environ['P1_TEST_MODEL_URL']+'/test/requests',trust_env=False).json()
                    if any(any(m.get('content')=='P2_CHILD restartbg' for m in b['messages']) for b in captured):break
                    time.sleep(.01)
                else:raise AssertionError('Background model did not enter the deterministic restart barrier')
                before=len(httpx.get(os.environ['P1_TEST_MODEL_URL']+'/test/requests',trust_env=False).json())
                backend.kill();backend.wait(timeout=5)
                httpx.post(os.environ['P1_TEST_MODEL_URL']+'/test/release/restartbg',trust_env=False).raise_for_status()
            # Seed a background orphan on this authorized new DB, preserving original IDs/state columns.
            with engine.begin() as c:
                c.execute(text("INSERT INTO ai_agent_background_task(session_id,task_id,type,status,agent_id,agent_type) VALUES('restart-effects','orphan-task','local_agent','running','orphan-agent','general-purpose')"))
            backend=start()
            assert client.get(acl_path).text=='persistent owner'
            if kb:assert client.post('/v1/documents/list_kb_files',json={'kb_id':kb}).status_code==200
            with httpx.Client(base_url=base,trust_env=False) as attacker:
                attacker.get('/api/agent/visitor/bootstrap')
                assert attacker.get(acl_path).status_code==403
                if kb:assert attacker.post('/v1/documents/list_kb_files',json={'kb_id':kb}).status_code==403
            history=client.get('/api/agent/conversation/sessions/restart-effects').json()['data']
            assert history['status']=='FAILED' and history['runs'][0]['requestId']=='restart-effects-a'
            assert 'follow_idle' in client.post('/api/agent/run/follow',json=dict(requestId='restart-effects-a')).text
            assert len(httpx.get(os.environ['P1_TEST_MODEL_URL']+'/test/requests',trust_env=False).json())==before
            with engine.connect() as c:
                assert c.execute(text("SELECT COUNT(*) FROM ai_agent_session_todo WHERE session_id='restart-effects'")).scalar()==1
                assert c.execute(text("SELECT error_code FROM ai_agent_dialogue_run WHERE request_id='restart-effects-a'")).scalar()=='PROCESS_RESTART'
                assert c.execute(text("SELECT COUNT(*) FROM ai_agent_llm_invocation l JOIN ai_agent_dialogue_run r ON r.id=l.run_id WHERE r.request_id='restart-effects-a' AND l.status=0")).scalar()==0
                assert c.execute(text("SELECT status FROM ai_agent_background_task WHERE task_id='orphan-task'")).scalar()=='failed'
                assert c.execute(text('SELECT status FROM ai_agent_user_question WHERE question_id=:q'),dict(q=question)).scalar()=='FAILED'
                assert c.execute(text("SELECT status FROM ai_agent_dialogue_run WHERE request_id='restart-bg-a'")).scalar()==1
                assert c.execute(text("SELECT status FROM ai_agent_background_task WHERE session_id='restart-bg'")).scalar()=='failed'
                receipt=c.execute(text("SELECT t.llm_oberserve FROM ai_agent_tool_invocation t JOIN ai_agent_dialogue_run r ON r.id=t.run_id WHERE r.request_id='restart-bg-a' AND t.tool_name='Agent'")).scalar()
                assert json.loads(receipt)['status']=='failed' and json.loads(receipt)['ok'] is False
                assert c.execute(text("SELECT COUNT(*) FROM ai_agent_llm_invocation l JOIN ai_agent_dialogue_run r ON r.id=l.run_id WHERE r.request_id='restart-bg-a' AND l.status=0")).scalar()==0
                assert c.execute(text("SELECT failed_run_count FROM ai_agent_dialogue_session WHERE session_id='restart-effects'")).scalar()==1
            assert not (isolation/'workspace/restart-bg/worker-restartbg.md').exists()
            refused=frames(client.post('/api/agent/ask-user/resume',json=dict(resumeRequestId=decided['resumeRequestId'])))
            assert refused[-1]['status']=='failed'
            # Success-before-markAnswered crash: startup reconciles with the durable RunB success.
            res=client.post('/web/api/v1/gpt/queryAgentStreamIncr',json=dict(sessionId='restart-success',requestId='restart-success-a',query='P2_ASK'))
            question2=payload(frames(res)[-1])['resultMap']['questionId']
            d=client.post('/api/agent/ask-user/answer',json=dict(questionId=question2,answers={'方向':'分析'})).json()['data']
            assert (await ledger.claim_interaction('question',v,d['resumeRequestId']))[1]
            with engine.begin() as c:
                c.execute(text("INSERT INTO ai_agent_dialogue_run(run_uid,request_id,session_id,visitor_id,entry_agent,status,query_text,started_at,finished_at) VALUES(:r,:r,'restart-success',:v,'react',1,'',NOW(3),NOW(3))"),dict(r=d['resumeRequestId'],v=v))
            backend.kill();backend.wait(timeout=5);backend=start()
            assert (await ledger.interaction('question',v,uid=question2))['status']=='ANSWERED'
            assert await ledger.settle_interaction('question',d['resumeRequestId'],'FAILED')==0
            evidence=dict(newDatabase=name,processKills=2,persistentFileOwner=True,persistentKbOwner=bool(kb),crossVisitorAfterRestart=403,originalRunPreserved=True,toolSideEffects=1,replayedRequests=0,
                          orphanRun='FAILED/PROCESS_RESTART',orphanBackground='failed',orphanClaim='FAILED',completedClaim='ANSWERED',
                          rootReturnedBeforeCrash='SUCCESS preserved; child failed; receipt failed; no tool replay')
            (isolation/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=10)
                except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
        for log in logs:log.close()
        await ledger.close();engine.dispose()
