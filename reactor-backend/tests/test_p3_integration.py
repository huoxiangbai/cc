"""P3 real TCP/isolated business MySQL/original Tool and local sandbox evidence."""
import hashlib
import json
import os
from pathlib import Path
import httpx
import pytest
from sqlalchemy import create_engine,text
from test_integration import env,client,query


def test_p3_01_nl2sql_actual_tool_generation_business_execution_files(env,client):
    response=client.post('/data/chatQuery',json={'content':'P3 查询各分类销售额'})
    assert response.status_code==200
    frames=[json.loads(l[5:]) for l in response.text.splitlines() if l.startswith('data:')]
    assert frames[-1]=={'eventType':'READY','data':''}
    errors=[f for f in frames if f['eventType']=='ERROR'];assert not errors,errors
    data=next(f['data'] for f in frames if f['eventType']=='CHART_DATA')
    assert data[0]['dataList']==[{'category':'A','total':30.0},{'category':'B','total':7.5}]
    assert data[0]['measureCols']==['total'] and data[0]['dimCols']==['category']
    assert 'sales' in data[0]['nl2sqlResult']
    rid=frames[0]['data'];r=client.post('/v1/file_tool/get_file_list',json={'requestId':rid}).json()
    assert {'query-1.csv','query-1-chart.json','query-provenance.json'}.issubset({f['fileName'] for f in r['results']})
    evidence={'model':'isolated HTTP fixture; original NL2SQLAgent generation logic','businessDB':os.environ['P3_BUSINESS_DB']+' new separate business source; actual SQL',
              'requestId':rid,'frames':frames,'files':[]}
    for f in r['results']:
        content=client.get(f['domainUrl']).content
        assert content
        evidence['files'].append({'fileName':f['fileName'],'previewUrl':f['domainUrl'],'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)})
    (env[0]/'p3-nl2sql-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
    assert client.get('/data/allModels').json()['data'][0]['modelCode']=='sales-model'
    assert client.get('/data/previewData',params={'modelCode':'sales-model'}).json()['data']['dataSize']==3
    assert client.post('/data/testQuery',json={'content':'DROP TABLE sales'}).status_code==500
    assert client.post('/data/vectorRecall',json={'query':'sales','modelCodeList':['sales-model']}).json()==[]
    assert client.post('/data/esRecall',json={'query':'sales','modelCodeList':['sales-model']}).json()==[]


def test_p3_02_actual_local_code_execution_agent_ledger_history(env,client):
    frames=query(client,'p3-local-code','p3-local-run','P3_LOCAL: 生成样本CSV并计算总额')
    assert frames[-1]['status']=='success',frames[-1]
    with env[3].connect() as c:
        row=c.execute(text("SELECT t.* FROM ai_agent_tool_invocation t JOIN ai_agent_dialogue_run r ON r.id=t.run_id WHERE r.request_id='p3-local-run'")).mappings().one()
        assert row['status']==1 and row['tool_name']=='code_execution'
        observation=json.loads(row['llm_oberserve']);assert observation['ok'] is True
        artifacts=[dict(r) for r in c.execute(text('SELECT * FROM ai_agent_artifact WHERE tool_invocation_id=:id'),{'id':row['id']}).mappings()]
    assert (env[0]/'workspace/p3-local-code/sales.csv').read_text().replace('\r','')=='category,amount\nA,30\nB,7.5\n'
    assert artifacts
    assert '37.5' in json.dumps(observation)
    for a in artifacts:assert client.get(a['download_url']).status_code==200
    history=client.get('/api/agent/conversation/sessions/p3-local-code').json()['data']
    assert history['runs'][0]['status']=='SUCCESS'
    (env[0]/'p3-code-evidence.json').write_text(json.dumps({'toolId':row['id'],'toolObservation':observation,'artifacts':artifacts,'history':history},default=str,ensure_ascii=False,indent=2))


def test_p3_03_actual_codeact_original_agent_sandbox_output_table(env,client):
    # Model fixture supplies code; ORIGINAL CIAgent validates/runs it and ORIGINAL sandbox writes actual files.
    with httpx.Client(base_url=env[1],cookies=client.cookies,timeout=120,trust_env=False) as c:
        frames=query(c,'p3-codeact','p3-codeact-run','P3_CODEACT: 分析分类销售额并交付CSV与报告')
    assert frames[-1]['status']=='success',frames[-1]
    with env[3].connect() as c:
        row=c.execute(text("SELECT o.*,t.status AS tool_status FROM ai_agent_tool_output_code_interpreter o JOIN ai_agent_tool_invocation t ON t.id=o.tool_invocation_id WHERE o.request_id='p3-codeact-run'")).mappings().one()
        assert row['tool_status']==1 and row['code_output']
        files=[dict(r) for r in c.execute(text('SELECT * FROM ai_agent_artifact WHERE tool_invocation_id=:id'),{'id':row['tool_invocation_id']}).mappings()]
    assert any('codeact-sales.csv' in f['file_name'] for f in files)
    for f in files:assert client.get(f['download_url']).content
    history=client.get('/api/agent/conversation/sessions/p3-codeact').json()['data']
    kinds=[f['resultMap']['eventData']['resultMap']['messageType'] for f in history['runs'][0]['replayFrames']]
    assert 'code' in kinds
    (env[0]/'p3-codeact-evidence.json').write_text(json.dumps({'output':dict(row),'artifacts':files,'frames':frames,'history':history},default=str,ensure_ascii=False,indent=2))

@pytest.mark.parametrize('platform',['twitter','reddit','xueqiu'])
def test_p3_04_original_social_credentials_missing_explicit_error(env,platform):
    response=httpx.post(env[2]+'/v1/tool/'+platform,json={'requestId':'p3-social','operation':'search','query':'样本'},headers={'X-Reactor-Service-Token':os.environ['P1_TEST_SERVICE_TOKEN']},trust_env=False)
    assert response.status_code==200
    data=response.json()['data'];assert data['ok'] is False and data['error']['code']


def test_p3_05_mrag_real_sqlite_history_routes(env):
    with httpx.Client(base_url=env[2],headers={'X-Reactor-Service-Token':os.environ['P1_TEST_SERVICE_TOKEN']},trust_env=False) as c:
        created=c.post('/v1/mrag/sessions/create',json={'title':'P3知识库历史','kb_id':'p3-kb'}).json()
        sid=created['data']['session_id']
        detail=c.post('/v1/mrag/sessions/detail',json={'session_id':sid}).json()
        assert detail['data']['session']['title']=='P3知识库历史' and detail['data']['turns']==[]
        listing=c.post('/v1/mrag/sessions/list',json={'page_no':1,'page_size':20}).json()
        assert any(s['session_id']==sid for s in listing['data']['list'])
        assert c.post('/v1/mrag/sessions/delete',json={'session_id':sid}).status_code==200


def test_p3_06_local_sandbox_permission_and_failure(env):
    root=env[0]/'workspace/p3-failure'
    with httpx.Client(base_url=env[2],headers={'X-Reactor-Service-Token':os.environ['P1_TEST_SERVICE_TOKEN']},timeout=10,trust_env=False) as c:
        def execute(source,**extra):return c.post('/v1/tool/code_execution',json={'requestId':'p3-failure','workspaceRoot':str(root),'source':source,'importTier':'stdlib',**extra}).json()
        assert execute('def broken(:')['status']=='error'
        assert execute("while True:\n    pass",timeoutSeconds=1)['status']=='timeout'
        ok=execute("print(2+3)");assert ok['status']=='ok' and '5' in ok['stdout']


def test_p3_07_local_sandbox_cross_workspace_denied(env):
    # Never print host file content. User authorized forwarding existing guard switches.
    r=httpx.post(env[2]+'/v1/tool/code_execution',json={'requestId':'p3-security','workspaceRoot':str(env[0]/'workspace/p3-security'),
        'source':"open('/etc/passwd').read()",'permissionProfile':'analysis','importTier':'stdlib'},headers={'X-Reactor-Service-Token':os.environ['P1_TEST_SERVICE_TOKEN']},trust_env=False)
    assert r.json()['status']=='error'


def test_p3_08_original_sop_missing_qdrant_and_real_sqlite_kb(env):
    with httpx.Client(base_url=env[2],headers={'X-Reactor-Service-Token':os.environ['P1_TEST_SERVICE_TOKEN']},trust_env=False) as c:
        result=c.post('/v1/sop/upsert',json={'sopName':'P3销售来源核对','sopDesc':'隔离样本','sopSteps':[{'title':'查询与交付','steps':['核对业务表','导出CSV']}],'status':'draft'})
        assert result.status_code==500 and 'Qdrant' in result.text
        sop={'verified':'original adapter rejects missing Qdrant; CRUD live unverified','response':result.json()}
        result=c.post('/v1/documents/create_knowledge_base',json={'kb_name':'P3证据库','kb_desc':'新建隔离库'})
        assert result.status_code==200,result.text
        kb=result.json()['data']
        listing=c.post('/v1/documents/list_knowledge_base',json={}).json()['data']['list']
        assert any(k['kb_id']==kb['kb_id'] for k in listing)
        (env[0]/'p3-sop-kb-evidence.json').write_text(json.dumps({'sop':sop,'kb':kb,'listing':listing},ensure_ascii=False,indent=2))


def test_p3_09_original_auto_analysis_get_data_real_sql_and_report(env,client):
    with httpx.Client(base_url=env[1],cookies=client.cookies,timeout=120,trust_env=False) as c:
        frames=query(c,'p3-analysis','p3-analysis-run','P3_DATA: 查询各分类销售额并交付来源报告',outputStyle='dataAgent')
    assert frames[-1]['status']=='success',frames[-1]
    with env[3].connect() as c:
        row=dict(c.execute(text("SELECT o.*,t.status AS tool_status FROM ai_agent_tool_output_data_analysis o JOIN ai_agent_tool_invocation t ON t.id=o.tool_invocation_id WHERE o.request_id='p3-analysis-run'")).mappings().one())
        files=[dict(r) for r in c.execute(text('SELECT * FROM ai_agent_artifact WHERE tool_invocation_id=:id'),{'id':row['tool_invocation_id']}).mappings()]
    assert row['tool_status']==1,row
    assert files and '30' in row['content'] and '7.5' in row['content']
    for f in files:assert client.get(f['download_url']).content
    (env[0]/'p3-analysis-evidence.json').write_text(json.dumps({'output':row,'files':files,'frames':frames},default=str,ensure_ascii=False,indent=2))
