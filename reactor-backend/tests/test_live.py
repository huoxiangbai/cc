"""Opt-in supplier verification with production adapter and NEW MySQL/tools only."""
import json
import os
from pathlib import Path
import httpx
import pytest
from sqlalchemy import create_engine,text


def test_real_supplier_tool_chain():
    if not os.environ.get('P1_TEST_ROOT'):
        pytest.skip('Requires integration.py --live-model and explicit supplier credentials')
    root=Path(os.environ['P1_TEST_ROOT'])
    assert (root/'ISOLATED_P1').is_file() and root.name.startswith(('reactor-p1-','reactor-p2-','reactor-p3-'))
    mysql_url=os.environ['P1_TEST_MYSQL_URL']
    assert 'reactor_p1_isolated' in mysql_url and 'unix_socket=' in mysql_url
    with httpx.Client(base_url=os.environ['P1_TEST_BACKEND_URL'],timeout=1200,trust_env=False) as c:
        assert c.get('/api/agent/visitor/bootstrap').json()['code']=='0000'
        assert c.post('/api/agent/visitor/naming',json={'username':'P1真实模型隔离验收'}).json()['code']=='0000'
        response=c.post('/web/api/v1/gpt/queryAgentStreamIncr',json=dict(sessionId='live-session-p1',requestId='live-request-p1',deepThink=0,
            query='必须调用text_processor：先write文件live-report.md，正文包含销售额125；再read该文件，确认文件内容后在最终回答引用文件并说明销售额。不要仅口头描述操作。'))
        frames=[json.loads(line[5:]) for line in response.text.splitlines() if line.startswith('data:')]
        assert frames and frames[-1]['status']=='success' and frames[-1]['finished']
        engine=create_engine(mysql_url,hide_parameters=True)
        try:
            with engine.connect() as db:
                run=db.execute(text("SELECT * FROM ai_agent_dialogue_run WHERE request_id='live-request-p1'")).mappings().one()
                tools=list(db.execute(text('SELECT * FROM ai_agent_tool_invocation WHERE run_id=:id'),{'id':run['id']}).mappings())
                artifacts=list(db.execute(text('SELECT * FROM ai_agent_artifact WHERE run_id=:id'),{'id':run['id']}).mappings())
            operations=[json.loads(t['input_json'])['operation'] for t in tools if t['tool_name']=='text_processor' and t['status']==1]
            assert 'write' in operations and 'read' in operations and run['status']==1 and artifacts
            for artifact in artifacts:
                for column in ('preview_url','download_url'):
                    result=httpx.get(artifact[column],trust_env=False,timeout=30)
                    assert result.status_code==200 and b'125' in result.content
            history=c.get('/api/agent/conversation/sessions/live-session-p1').json()['data']
            assert history['runs'][0]['replayFrames'] and history['status']=='SUCCESS'
            # No provider key or prompt transcript is exported in this summary.
            (root/'live-evidence.json').write_text(json.dumps(dict(runId=run['id'],llmCount=run['llm_call_count'],
                toolIds=[t['id'] for t in tools],artifactIds=[a['id'] for a in artifacts],operations=operations,status='PASS'),indent=2)+'\n')
        finally:
            engine.dispose()
