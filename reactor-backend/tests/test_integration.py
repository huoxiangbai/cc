"""Actual TCP + isolated MySQL + original Tool/file routes; model alone is fixed."""
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse
import httpx
import pytest
from sqlalchemy import create_engine,text
from reactor_backend.projection.history import replay
from model_service import CONTENT

@pytest.fixture(scope='module')
def env():
    if not os.environ.get('P1_TEST_ROOT'): pytest.skip('Run integration.py to provision a NEW isolated database')
    root=Path(os.environ['P1_TEST_ROOT'])
    assert root.name.startswith(('reactor-p1-','reactor-p2-','reactor-p3-','reactor-p4-','reactor-p5-')) and (root/'ISOLATED_P1').is_file()
    url=os.environ['P1_TEST_MYSQL_URL']
    assert 'reactor_p1_isolated' in url and 'unix_socket=' in url
    return root,os.environ['P1_TEST_BACKEND_URL'],os.environ['P1_TEST_TOOL_URL'],create_engine(url,hide_parameters=True)

@pytest.fixture(scope='module')
def client(env):
    with httpx.Client(base_url=env[1],timeout=30,trust_env=False) as c:
        bootstrap=c.get('/api/agent/visitor/bootstrap')
        assert bootstrap.status_code==200
        assert bootstrap.json()['data']['named'] is False
        assert 'HttpOnly' in bootstrap.headers['set-cookie']
        name=c.post('/api/agent/visitor/naming',json={'username':'P1隔离用户'})
        assert name.json()['data']['named'] is True
        yield c


def query(c,session,request,content,**extra):
    response=c.post('/web/api/v1/gpt/queryAgentStreamIncr',json={'sessionId':session,'requestId':request,'query':content,'deepThink':0,**extra})
    assert response.status_code==200
    assert 'event:' not in response.text and '[DONE]' not in response.text
    assert 'text/event-stream' in response.headers['content-type']
    events=[json.loads(line[5:]) for line in response.text.splitlines() if line.startswith('data:')]
    assert events[-1]['finished'] is True
    return events


def test_01_real_tool_to_sse_ledger_artifact_and_refresh(env,client):
    events=query(client,'session-real-p1','request-real-p1','生成报告并读取核实销售额125')
    assert events[-1]['status']=='success'
    assert [f['eventSeq'] for f in events] == list(range(1,len(events)+1))
    kinds=[f['resultMap']['eventData']['resultMap']['messageType'] for f in events]
    assert kinds.count('tool_call')==2 and kinds.count('tool_result')==2 and 'file' in kinds
    assert events[-1]['resultMap']['eventData']['resultMap']['result'].endswith('销售额125。')
    with env[3].connect() as c:
        run=dict(c.execute(text("SELECT * FROM ai_agent_dialogue_run WHERE request_id='request-real-p1'")).mappings().one())
        llms=[dict(x) for x in c.execute(text('SELECT * FROM ai_agent_llm_invocation WHERE run_id=:id ORDER BY invocation_seq'),{'id':run['id']}).mappings()]
        tools=[dict(x) for x in c.execute(text('SELECT * FROM ai_agent_tool_invocation WHERE run_id=:id ORDER BY id'),{'id':run['id']}).mappings()]
        artifacts=[dict(x) for x in c.execute(text('SELECT * FROM ai_agent_artifact WHERE run_id=:id'),{'id':run['id']}).mappings()]
    assert run['status']==1 and run['llm_call_count']==3 and run['tool_call_count']==2 and run['artifact_count']==1
    assert run['total_tokens_total']==90
    assert [x['llm_invocation_id'] for x in tools]==[llms[0]['id'],llms[1]['id']]
    assert artifacts[0]['tool_invocation_id']==tools[0]['id'] and artifacts[0]['tool_call_id']=='call-p1-write'
    assert artifacts[0]['request_id']==run['request_id']
    assert (env[0]/'workspace/session-real-p1/报告.md').read_text()==CONTENT
    for column in ('preview_url','download_url'):
        r=client.get(artifacts[0][column]); assert r.status_code==200 and r.content==CONTENT.encode()
    sessions=client.get('/api/agent/conversation/sessions').json()['data']
    assert any(s['sessionId']=='session-real-p1' and s['runCount']==1 for s in sessions)
    detail=client.get('/api/agent/conversation/sessions/session-real-p1').json()['data']
    assert detail['status']=='SUCCESS' and detail['runs'][0]['finalSummaryText'].endswith('销售额125。')
    assert len(detail['runs'][0]['replayFrames'])>=3
    facts=dict(run=run,llms=llms,tools=tools,artifacts=artifacts)
    # Export actual database rows, with links/IDs retained, for original Java read-side replay comparison.
    (env[0]/'facts.json').write_text(json.dumps(facts,default=str,ensure_ascii=False,indent=2))
    (env[0]/'python-replay.json').write_text(json.dumps(replay(facts),ensure_ascii=False,indent=2))
    (env[0]/'evidence.json').write_text(json.dumps(dict(requestId=run['request_id'],sessionId=run['session_id'],runId=run['id'],
        llmIds=[l['id'] for l in llms],toolIds=[t['id'] for t in tools],artifactIds=[a['id'] for a in artifacts],
        previewBytes=len(CONTENT.encode()),downloadBytes=len(CONTENT.encode()),sseKinds=kinds),ensure_ascii=False,indent=2))


def test_02_cross_turn_mysql_context(env,client):
    events=query(client,'session-real-p1','request-second-p1','SECOND_TURN 请引用上一轮')
    assert '跨轮上下文已读取' in events[-1]['resultMap']['eventData']['resultMap']['result']
    history=client.get('/api/agent/conversation/sessions/session-real-p1').json()['data']
    assert history['runCount']==2 and history['finishedRunCount']==2 and len(history['runs'])==2


def test_03_real_tool_failure_is_observation(env,client):
    events=query(client,'session-fail-p1','request-fail-p1','TOOL_FAIL')
    assert events[-1]['status']=='success'  # Model handled a real failed tool, not a false successful tool.
    with env[3].connect() as c:
        t=c.execute(text("SELECT t.* FROM ai_agent_tool_invocation t JOIN ai_agent_dialogue_run r ON r.id=t.run_id WHERE r.request_id='request-fail-p1'")).mappings().one()
        assert t['status']==2 and t['llm_oberserve'].startswith('Error: ')
        assert '不存在' in t['error_msg'] or 'No such file' in t['error_msg'] or 'File not found' in t['error_msg']


def test_04_model_failure_persisted(env,client):
    events=query(client,'session-model-fail','request-model-fail','MODEL_FAIL')
    assert events[-1]['status']=='failed' and '401' in events[-1]['errorMsg']
    with env[3].connect() as c:
        r=c.execute(text("SELECT * FROM ai_agent_dialogue_run WHERE request_id='request-model-fail'")).mappings().one()
        assert r['status']==2 and r['finished_at'] and r['tool_call_count']==0
        assert c.execute(text('SELECT status FROM ai_agent_llm_invocation WHERE run_id=:id'),{'id':r['id']}).scalar()==2


def test_05_tcp_disconnect_does_not_cancel_and_follow(env,client):
    with client.stream('POST','/web/api/v1/gpt/queryAgentStreamIncr',json={'sessionId':'session-disconnect','requestId':'request-disconnect','query':'DISCONNECT'}) as r:
        for line in r.iter_lines():
            if line.startswith('data:'):
                cursor=json.loads(line[5:])['eventSeq'];break
    # A real TCP disconnect, followed by rebind using the original cursor, never re-POST query.
    response=client.post('/api/agent/run/follow',json={'sessionId':'session-disconnect','requestId':'request-disconnect','lastEventSeq':cursor})
    assert response.status_code==200
    for _ in range(80):
        detail=client.get('/api/agent/conversation/sessions/session-disconnect').json()['data']
        if detail['status']=='SUCCESS': break
        time.sleep(.05)
    else: pytest.fail('Disconnected business run did not complete')
    assert detail['runCount']==1 and '125' in detail['runs'][0]['finalSummaryText']
    idle=client.post('/api/agent/run/follow',json={'requestId':'request-disconnect','sessionId':'session-disconnect'})
    assert 'follow_idle' in idle.text


def test_06_identity_owner_and_binding_errors(env,client):
    repeat=client.post('/api/agent/visitor/naming',json={'username':'changed'})
    assert repeat.json()['code']=='0002'
    with httpx.Client(base_url=env[1],timeout=30,trust_env=False) as other:
        denied=other.get('/api/agent/conversation/sessions/session-real-p1').json()
        assert denied['code']=='0001' and denied['data'] is None
        denied_stream=query(other,'session-real-p1','request-foreign-p1','attempt')
        assert denied_stream[-1]['status']=='failed'
        assert other.get('/api/agent/conversation/sessions').json()['data']==[]
    assert client.post('/web/api/v1/gpt/queryAgentStreamIncr',content='{broken',headers={'Content-Type':'application/json'}).status_code==400
    assert client.post('/web/api/v1/gpt/queryAgentStreamIncr',json={'deepThink':{}}).status_code==400
    assert client.get('/api/agent/conversation/sessions?limit=invalid').status_code==400


def test_07_original_java_fixture_in_mysql(env,client):
    # This is the P0 synthetic Java dataset, NOT a claimed old user-data copy.
    visitor=client.get('/api/agent/visitor/bootstrap').json()['data']['visitorId']
    with env[3].begin() as c:
        c.execute(text("INSERT INTO ai_agent_dialogue_session(session_id,visitor_id,title,status,run_count,finished_run_count,started_at,last_active_at) VALUES('session-history-p0',:visitor,'中文历史',1,1,1,'2026-10-02 22:00:00','2026-10-02 22:00:03')"),{'visitor':visitor})
        c.execute(text("INSERT INTO ai_agent_dialogue_run(run_uid,request_id,session_id,entry_agent,status,query_text,final_summary_text,started_at,finished_at) VALUES('req-history-p0','req-history-p0','session-history-p0','react',1,'中文历史','history summary','2026-10-02 22:00:00','2026-10-02 22:00:03')"))
    detail=client.get('/api/agent/conversation/sessions/session-history-p0').json()['data']
    assert detail['deepThink'] is False and detail['runs'][0]['replayFrames'][-1]['resultMap']['eventData']['resultMap']['result']=='history summary'


def test_08_old_genui_tables_replay(env,client):
    visitor=client.get('/api/agent/visitor/bootstrap').json()['data']['visitorId']
    tree={'schemaVersion':'1','root':{'nodeId':'old-root','kind':'Stat','props':{'value':'旧Java画布'},'children':[]}}
    patches=[{'op':'replace','path':'/root/props/value','value':'回放补丁'}]
    with env[3].begin() as c:
        c.execute(text("INSERT INTO ai_agent_dialogue_session(session_id,visitor_id,title,status,run_count,finished_run_count,started_at,last_active_at) VALUES('session-genui-p1',:visitor,'旧画布',1,1,1,'2026-10-02 22:00:00','2026-10-02 22:00:03')"),{'visitor':visitor})
        run_id=c.execute(text("INSERT INTO ai_agent_dialogue_run(run_uid,request_id,session_id,entry_agent,status,query_text,started_at,finished_at) VALUES('req-genui-p1','req-genui-p1','session-genui-p1','react',1,'旧画布','2026-10-02 22:00:00','2026-10-02 22:00:03')")).lastrowid
        llm_id=c.execute(text("INSERT INTO ai_agent_llm_invocation(run_id,invocation_seq,agent_name,call_kind,tool_call_count,status,started_at,finished_at) VALUES(:run,1,'react','askTool',2,1,'2026-10-02 22:00:00','2026-10-02 22:00:01')"),{'run':run_id}).lastrowid
        for i,(name,params) in enumerate([('emit_ui_tree',{'tree':tree}),('emit_ui_patch',{'canvas_id':'old-canvas','seq':2,'patches':patches})]):
            tool_id=c.execute(text("INSERT INTO ai_agent_tool_invocation(run_id,llm_invocation_id,tool_call_id,dispatch_index,agent_name,tool_name,input_json,status,started_at,finished_at) VALUES(:run,:llm,:call,:index,'react',:name,:params,1,'2026-10-02 22:00:01','2026-10-02 22:00:02')"),dict(run=run_id,llm=llm_id,call='old-genui-'+str(i),index=i,name=name,params=json.dumps(params))).lastrowid
            if i==0:
                c.execute(text("INSERT INTO ai_agent_tool_output_emit_ui_tree(tool_invocation_id,run_id,request_id,session_id,tool_call_id,status,canvas_id,tree_json) VALUES(:tool,:run,'req-genui-p1','session-genui-p1','old-genui-0',1,'old-canvas',:tree)"),dict(tool=tool_id,run=run_id,tree=json.dumps(tree)))
    detail=client.get('/api/agent/conversation/sessions/session-genui-p1').json()['data']
    frames=detail['runs'][0]['replayFrames']
    payloads=[f['resultMap']['eventData']['resultMap'] for f in frames]
    assert payloads[0]['messageType']=='ui_tree' and payloads[0]['resultMap']['tree']==tree
    assert payloads[0]['resultMap']['canvas_id']=='old-canvas'
    assert payloads[1]['messageType']=='ui_patch' and payloads[1]['resultMap']['patches']==patches and payloads[1]['resultMap']['seq']==2
    with env[3].connect() as c:
        run=dict(c.execute(text('SELECT * FROM ai_agent_dialogue_run WHERE id=:id'),{'id':run_id}).mappings().one())
        llms=[dict(l) for l in c.execute(text('SELECT * FROM ai_agent_llm_invocation WHERE run_id=:id'),{'id':run_id}).mappings()]
        tools=[dict(t) for t in c.execute(text('SELECT * FROM ai_agent_tool_invocation WHERE run_id=:id ORDER BY dispatch_index'),{'id':run_id}).mappings()]
        for t in tools:
            if t['tool_name']=='emit_ui_tree': t['structured_output']=dict(c.execute(text('SELECT * FROM ai_agent_tool_output_emit_ui_tree WHERE tool_invocation_id=:id'),{'id':t['id']}).mappings().one())
    (env[0]/'genui-facts.json').write_text(json.dumps(dict(run=run,llms=llms,tools=tools,artifacts=[]),default=str,ensure_ascii=False,indent=2))
    (env[0]/'genui-python-replay.json').write_text(json.dumps(frames,ensure_ascii=False,indent=2))


def test_09_real_mysql_model_binding_and_context_window(env,client):
    with env[3].begin() as c:
        c.execute(text("INSERT INTO ai_client_api(api_id,base_url,api_key,completions_path,embeddings_path,status) VALUES('api-test-p1',:url,'isolation-test-key','/v1/chat/completions','/v1/embeddings',1)"),{'url':os.environ['P1_TEST_MODEL_URL']})
        model_id=c.execute(text("INSERT INTO ai_client_model(model_id,api_id,model_usage,model_name,model_type,context_window,status) VALUES('model-db-p1','api-test-p1','default','p1-fixed-upstream','openai',32768,1)")).lastrowid
    response=client.post('/web/api/v1/gpt/queryAgentStreamIncr',json=dict(sessionId='session-db-model',requestId='request-db-model',query='真实DB模型绑定',model='__db_binding__:'+str(model_id)))
    events=[json.loads(line[5:]) for line in response.text.splitlines() if line.startswith('data:')]
    assert events[-1]['status']=='success'
    history=client.get('/api/agent/conversation/sessions/session-db-model').json()['data']
    assert history['runs'][0]['contextUsage']['max']==32768
    assert client.post('/api/agent/visitor/naming',json={'username':{}}).status_code==400


def test_10_original_rich_tool_tables_replay(env,client):
    from reactor_backend.models.tool_outputs import OUTPUT_TABLES
    visitor=client.get('/api/agent/visitor/bootstrap').json()['data']['visitorId']
    stages=[dict(stage='extend',queries=['事实']),dict(stage='search',results=[dict(query='事实',docs=[dict(title='来源',link='https://example.com',summary='内容')])]),
            dict(stage='chapter_summary',chapterId='chapter-1',chapterTitle='章',chapterContent='正文',chapterOrder=1,queries=['事实'],chapterSummary='摘要'),dict(stage='report',answer='最终研究')]
    outputs=[('code_interpreter',dict(code_output='python output',content='内容',code='print(1)',explain='解释')),
        ('data_analysis',dict(task='任务',content='分析正文')),('multimodalagent_tool',dict(summary='多模态摘要',markdown_content='# 正文')),
        ('canvas_publish',dict(title='旧画布',primary_file_name='report.html',preview_url='https://example.com/p',download_url='https://example.com/d')),
        ('image_generation_tool',dict(request_source='agent',summary='旧图片')),('deep_search',dict(query='研究',stages_json=json.dumps(stages))),
        ('AskUserQuestion',None)]
    with env[3].begin() as c:
        c.execute(text("INSERT INTO ai_agent_dialogue_session(session_id,visitor_id,title,status,run_count,finished_run_count,started_at,last_active_at) VALUES('session-rich-p1',:visitor,'旧专用工具',1,1,1,'2026-10-02 22:00:00','2026-10-02 22:00:03')"),{'visitor':visitor})
        run_id=c.execute(text("INSERT INTO ai_agent_dialogue_run(run_uid,request_id,session_id,entry_agent,status,query_text,started_at,finished_at) VALUES('req-rich-p1','req-rich-p1','session-rich-p1','react',1,'旧专用工具','2026-10-02 22:00:00','2026-10-02 22:00:03')")).lastrowid
        llm_id=c.execute(text("INSERT INTO ai_agent_llm_invocation(run_id,invocation_seq,agent_name,call_kind,tool_call_count,status,started_at,finished_at) VALUES(:run,1,'react','askTool',7,1,'2026-10-02 22:00:00','2026-10-02 22:00:01')"),{'run':run_id}).lastrowid
        for i,(name,output) in enumerate(outputs):
            call='old-rich-'+str(i)
            observation=json.dumps(dict(questionId='old-question',questions=[dict(header='选择',question='确认',options=[])],answers={'选择':'是'})) if output is None else 'original observation'
            tool_id=c.execute(text("INSERT INTO ai_agent_tool_invocation(run_id,llm_invocation_id,tool_call_id,dispatch_index,agent_name,tool_name,input_json,llm_oberserve,status,started_at,finished_at) VALUES(:run,:llm,:call,:index,'react',:name,'{}',:obs,1,'2026-10-02 22:00:01','2026-10-02 22:00:02')"),dict(run=run_id,llm=llm_id,call=call,index=i,name=name,obs=observation)).lastrowid
            if output is not None:
                value=dict(tool_invocation_id=tool_id,run_id=run_id,request_id='req-rich-p1',session_id='session-rich-p1',tool_call_id=call,status=1,**output)
                columns=','.join('`'+key+'`' for key in value);values=','.join(':'+key for key in value)
                c.execute(text(f'INSERT INTO ai_agent_tool_output_{OUTPUT_TABLES[name]}({columns}) VALUES({values})'),value)
            if name in ('image_generation_tool','deep_search','code_interpreter'):
                c.execute(text("INSERT INTO ai_agent_artifact(run_id,request_id,tool_invocation_id,tool_call_id,artifact_role,visibility,source_type,source_name,file_name,storage_key,preview_url,download_url,file_size) VALUES(:run,'req-rich-p1',:tool,:call,'output','visible','tool_output',:name,'报告.md',:key,'https://example.com/p','https://example.com/d',74)"),dict(run=run_id,tool=tool_id,call=call,name=name,key='rich-output-'+str(i)))
    detail=client.get('/api/agent/conversation/sessions/session-rich-p1').json()['data']
    frames=detail['runs'][0]['replayFrames']
    assert [f['resultMap']['eventData']['resultMap']['messageType'] for f in frames]==['code','data_analysis','markdown','html','file','tool_result','deep_search','deep_search','deep_search','deep_search','ask_user_question']
    assert frames[-1]['resultMap']['eventData']['resultMap']['resultMap']['status']=='answered'
    with env[3].connect() as c:
        run=dict(c.execute(text('SELECT * FROM ai_agent_dialogue_run WHERE id=:id'),{'id':run_id}).mappings().one())
        llms=[dict(l) for l in c.execute(text('SELECT * FROM ai_agent_llm_invocation WHERE run_id=:id'),{'id':run_id}).mappings()]
        tools=[dict(t) for t in c.execute(text('SELECT * FROM ai_agent_tool_invocation WHERE run_id=:id ORDER BY dispatch_index'),{'id':run_id}).mappings()]
        for t in tools:
            if t['tool_name'] in OUTPUT_TABLES:
                t['structured_output']=dict(c.execute(text(f'SELECT * FROM ai_agent_tool_output_{OUTPUT_TABLES[t["tool_name"]]} WHERE tool_invocation_id=:id'),{'id':t['id']}).mappings().one())
        artifacts=[dict(a) for a in c.execute(text('SELECT * FROM ai_agent_artifact WHERE run_id=:id ORDER BY id'),{'id':run_id}).mappings()]
    (env[0]/'rich-facts.json').write_text(json.dumps(dict(run=run,llms=llms,tools=tools,artifacts=artifacts),default=str,ensure_ascii=False,indent=2))
    (env[0]/'rich-python-replay.json').write_text(json.dumps(frames,ensure_ascii=False,indent=2))
