"""P4 HTTP/SSE, original MySQL and original Sandbox on integration.py's NEW root."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import time
import httpx
import pytest
from sqlalchemy import create_engine,text
from reactor_backend.adapters.mysql import MySQLLedger,insert,rows
from reactor_backend.models.types import Query,ModelReply,ToolCall
from reactor_backend.memory.service import Memory
from reactor_backend.runtime.local_tools import ToolScope
from reactor_backend.runtime.control import RunControl
from reactor_backend.runtime.react import ReAct
from reactor_backend.bootstrap.config import Settings
from reactor_backend.memory.working import groups


@pytest.fixture(scope='module')
def env():
    if not os.environ.get('P1_TEST_ROOT'):pytest.skip('Use integration.py --phase p4')
    root=Path(os.environ['P1_TEST_ROOT']);assert root.name.startswith('reactor-p4-') and (root/'ISOLATED_P1').exists()
    return root,os.environ['P1_TEST_BACKEND_URL'],create_engine(os.environ['P1_TEST_MYSQL_URL'],hide_parameters=True)


@pytest.fixture(scope='module')
def client(env):
    with httpx.Client(base_url=env[1],trust_env=False,timeout=90) as c:
        c.get('/api/agent/visitor/bootstrap');c.post('/api/agent/visitor/naming',json={'username':'P4真实流程'})
        yield c


def query(c,session,request,content):
    r=c.post('/web/api/v1/gpt/queryAgentStreamIncr',json=dict(sessionId=session,requestId=request,query=content,deepThink=0))
    assert r.status_code==200,r.text
    events=[json.loads(l[5:]) for l in r.text.splitlines() if l.startswith('data:')]
    assert events[-1]['finished'] and not any(e.get('errorMsg') for e in events),events[-1]
    return events


def test_01_memory_tool_durable_cross_turn_and_foreign_visitor_denied(env,client):
    query(client,'p4-memory-session','p4-memory-1','P4_MEMORY 用户需要跨轮记忆')
    query(client,'p4-memory-session','p4-memory-2','P4_CONTINUE 继续')
    captured=httpx.get(os.environ['P1_TEST_MODEL_URL']+'/test/requests',trust_env=False).json()
    assert any('P4 用户偏好中文报告' in str(r['messages'][0]) and any(m.get('content')=='P4_CONTINUE 继续' for m in r['messages']) for r in captured)
    with env[2].begin() as c:
        entries=rows(c,"SELECT * FROM ai_agent_ltm_curated_entry WHERE source_session_id='p4-memory-session' AND deleted=0")
        assert any(e['scope']=='user' for e in entries)
    with httpx.Client(base_url=env[1],trust_env=False) as other:
        other.get('/api/agent/visitor/bootstrap');other.post('/api/agent/visitor/naming',json={'username':'隔离负例'})
        query(other,'p4-foreign-session','p4-foreign-run','P4_CONTINUE 外来用户')
    captured=httpx.get(os.environ['P1_TEST_MODEL_URL']+'/test/requests',trust_env=False).json()
    req=next(r for r in captured if any(m.get('content')=='P4_CONTINUE 外来用户' for m in r['messages']))
    assert 'P4 用户偏好中文报告' not in str(req['messages'])


def test_02_original_skill_script_real_sandbox_package_and_global_unchanged(env,client):
    source=env[0]/'skills/skill-creator/scripts/package_skill.py';original=source.read_bytes()
    events=query(client,'p4-skill-session','p4-skill-run','P4_SKILL '+str(Path(__file__).parents[1]/'.venv/bin/python'))
    with env[2].begin() as c:
        bash=rows(c,"SELECT * FROM ai_agent_tool_invocation WHERE run_id=(SELECT id FROM ai_agent_dialogue_run WHERE request_id='p4-skill-run') AND tool_name='bash'")[0]
        value=json.loads(bash['llm_oberserve']);assert value['exit_code']==0,value
        assert 'Successfully packaged skill' in value['stdout'],value
        artifacts=rows(c,"SELECT * FROM ai_agent_artifact WHERE request_id='p4-skill-run'")
        assert any(a['file_name'].endswith('.skill') for a in artifacts)
    assert source.read_bytes()==original and not (env[0]/'skills/p4-created').exists()
    assert any(e['resultMap']['eventData']['resultMap']['messageType']=='file' for e in events)


def test_03_three_mcp_via_agent_sse_and_original_wire_names(env,client):
    query(client,'p4-mcp-session','p4-mcp-run','P4_MCP 三传输调用')
    with env[2].begin() as c:
        inv=rows(c,"SELECT * FROM ai_agent_tool_invocation WHERE run_id=(SELECT id FROM ai_agent_dialogue_run WHERE request_id='p4-mcp-run') ORDER BY dispatch_index,id")
        actual=[r for r in inv if r['tool_name'].startswith('mcp__')]
        assert len(actual)==3
        for r in actual:assert r['status']==1 and 'original.echo!' in r['llm_oberserve'] and '真实P4参数' in r['llm_oberserve']
        assert any(r['tool_name']=='ReadMcpResource' and '真实 MCP resource' in r['llm_oberserve'] for r in inv)


def test_04_java_shape_old_working_memory_hydrate_and_search(env,client):
    query(client,'p4-old-session','p4-old-create','P4_CONTINUE 建立隔离会话')
    with env[2].begin() as c:
        run=rows(c,"SELECT * FROM ai_agent_dialogue_run WHERE request_id='p4-old-create'")[0]
        projected=json.loads((env[0]/'java-memory.json').read_text())
        seq=rows(c,"SELECT MAX(turn_seq)+1 AS n FROM ai_agent_working_memory_turn WHERE session_id='p4-old-session'")[0]['n']
        turn=insert(c,'working_memory_turn',dict(session_id=run['session_id'],request_id='p4-java-old-projection',run_id=run['id'],turn_seq=seq,entry_agent='react',memory_scope='main',status=1,message_count=len(projected)))
        def snake(value):
            import re
            return re.sub(r'(?<!^)(?=[A-Z])','_',value).lower()
        for old in projected:
            record={snake(k):v for k,v in old.items() if k not in ('id','turnId','createTime','updateTime')}
            record['turn_id']=turn;record['run_id']=run['id'];insert(c,'working_memory_message',record)
    query(client,'p4-old-session','p4-old-continue','P4_CONTINUE 续轮旧记录')
    query(client,'p4-old-session','p4-old-search','P4_SEARCH 旧轮证据')
    captured=httpx.get(os.environ['P1_TEST_MODEL_URL']+'/test/requests',trust_env=False).json()
    req=next(r for r in captured if any(m.get('content')=='P4_CONTINUE 续轮旧记录' for m in r['messages']))
    assert '旧工具成功：125' in str(req['messages']);groups(req['messages'][1:])
    assert any(m.get('reasoning_content')=='old model reasoning' for m in req['messages'])
    async def check_scopes():
        ledger=MySQLLedger(os.environ['P1_TEST_MYSQL_URL'])
        try:
            def seed(c):
                run=rows(c,"SELECT * FROM ai_agent_dialogue_run WHERE request_id='p4-old-create'")[0]
                ledger._save_context(c,{**run,'request_id':'old-child'},[{'role':'user','content':'Java子侧链'}],'sub:legacy-child')
                ledger._save_context(c,{**run,'request_id':'p2-child'},[{'role':'assistant','content':'Python旧侧链'}],'subagent:legacy-child')
            await ledger.transact(seed)
            assert [m['content'] for m in await ledger.context('p4-old-session','sub:legacy-child')]==['Java子侧链','Python旧侧链']
            assert 'Java子侧链' not in str(await ledger.context('p4-old-session'))
        finally:await ledger.close()
    asyncio.run(check_scopes())
    with env[2].begin() as c:
        observation=rows(c,"SELECT llm_oberserve FROM ai_agent_tool_invocation WHERE run_id=(SELECT id FROM ai_agent_dialogue_run WHERE request_id='p4-old-search') AND tool_name='session_search'")[0]['llm_oberserve']
        assert '旧轮证据' in observation and 'match_message_id' in observation and json.loads(observation)['search_backend']=='fulltext'


@pytest.mark.parametrize('mode',['success','P4_PERMANENT_FAIL','P4_TRANSIENT_FAIL'])
def test_05_large_old_context_compaction_and_failed_summary_continuation(env,client,mode):
    sid='p4-compact-'+mode;rid='p4-new-'+mode
    query(client,sid,'p4-init-'+mode,'P4_CONTINUE 初始化')
    source=[{'role':'user','content':mode+' 旧轮证据'+str(i)+'x'*18000} if i%2==0 else {'role':'assistant','content':'真实历史答案 '+str(i)+'y'*18000} for i in range(30)]
    with env[2].begin() as c:
        run=rows(c,'SELECT * FROM ai_agent_dialogue_run WHERE session_id=:s ORDER BY id DESC LIMIT 1',s=sid)[0]
        MySQLLedger._save_context(c,{**run,'request_id':'p4-source-'+mode},source)
    query(client,sid,rid,'P4_CONTINUE 最新问题保持可用')
    with env[2].begin() as c:
        events=rows(c,'SELECT * FROM ai_agent_working_memory_compaction WHERE trigger_request_id=:r',r=rid)
        assert events
        event=events[-1]
        if mode=='P4_PERMANENT_FAIL':assert event['strategy']=='abort-unchanged' and event['status']==2
        else:assert event['after_tokens']<event['before_tokens']
        if mode!='P4_PERMANENT_FAIL':assert rows(c,"SELECT id FROM ai_agent_working_memory_turn WHERE session_id=:s AND status=2",s=sid)
        else:assert event['compact_request_id'] is None
    query(client,sid,'p4-next-'+mode,'P4_CONTINUE 第二次续轮')


async def test_06_curated_capacity_ambiguity_batch_fork_whitelist_and_scope(env,client):
    ledger=MySQLLedger(os.environ['P1_TEST_MYSQL_URL'])
    with env[2].begin() as c:owner=rows(c,"SELECT visitor_id FROM ai_agent_dialogue_session WHERE session_id='p4-memory-session'")[0]['visitor_id']
    q=Query('p4-curated-unit','p4-memory-session',owner,'query','trace','user',1)
    try:
        a=await ledger.memory_mutate(q,{'action':'add','target':'curated','content':'entry-one shared'});assert a['success']
        await ledger.memory_mutate(q,{'action':'add','target':'curated','content':'entry-two shared'})
        assert not (await ledger.memory_mutate(q,{'action':'remove','target':'curated','old_text':'shared'}))['success']
        assert not (await ledger.memory_mutate(q,{'action':'add','target':'user','content':'x'*1400}))['success']
        with pytest.raises(ValueError,match='无权'):await ledger.memory_entries(replace(q,visitor_id='wrong-visitor'))
        with pytest.raises(ValueError,match='无权'):await ledger.session_search(q,{'session_id':'p4-foreign-session'})
        assert (await ledger.session_search(q,{'session_id':q.session_id}))['mode']=='read'
        discovery=await ledger.session_search(q,{'query':'旧轮证据','scope':'user'})
        match=next(s for s in discovery['results'] if s['session_id']=='p4-old-session')
        scroll=await ledger.session_search(q,{'session_id':match['session_id'],'around_message_id':match['match_message_id'],'window':1});assert scroll['mode']=='scroll'
        attempts=[]
        class Model:
            async def complete(self,m,t,query):
                attempts.append((m,t))
                if len(attempts)==1:return ModelReply(calls=[ToolCall('deny','bash','{"command":"touch evil"}'),ToolCall('mem','memory','{"action":"add","target":"curated","content":"fork whitelist evidence"}')])
                return ModelReply(content='done')
        class Tools:schemas=[]
        runtime=ReAct(ledger,Model(),Tools(),Settings('unused','unused',env[0]/'fork-work',memory_settings={}))
        scope=ToolScope(runtime,RunControl(q,None),q)
        parent=[{'role':'system','content':'exact frozen parent'},{'role':'user','content':'historical input'}];schemas=scope.visible()
        result=await runtime.memory.fork(scope,parent,schemas,'flush');assert result['status']==1
        assert attempts[0][0][0]==parent[0] and attempts[0][1]==schemas and attempts[0][0][1]==parent[1]
        assert 'Memory-only fork' in str(attempts[1][0]) and not (env[0]/'fork-work'/q.session_id/'evil').exists()
        child=ToolScope(runtime,RunControl(q,None),q,child={'subAgentId':'isolated'},definition={'allowed_tools_json':'["*"]'})
        assert (await runtime.memory.execute(child,'memory',{'action':'add','target':'curated','content':'child denied'})).failed
    finally:await ledger.close()
