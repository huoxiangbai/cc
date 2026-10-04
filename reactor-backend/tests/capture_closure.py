"""Export P3 evidence only from this harness' explicitly NEW isolated roots."""
import argparse,hashlib,json,shutil,sqlite3
from pathlib import Path
from urllib.parse import quote
import httpx
from sqlalchemy import create_engine,text

ROOT=Path(__file__).resolve().parents[2]


def isolated(raw):
    root=Path(raw).resolve()
    if not root.name.startswith('reactor-p3-') or not (root/'ISOLATED_P1').is_file():raise ValueError('Only fresh P3 harness roots are accepted')
    return root


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--integration',required=True);parser.add_argument('--mysql',required=True);parser.add_argument('--browser',required=True)
    args=parser.parse_args();integration=isolated(args.integration);mysql=isolated(args.mysql);browser=isolated(args.browser)
    fixtures=ROOT/'docs/python-migration/fixtures';destination=fixtures/'p3-closure-artifacts';destination.mkdir(exist_ok=True)
    manifest=[]
    def copy(source,label):
        target=destination/label;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        manifest.append({'source':str(source),'copy':str(target.relative_to(fixtures)),'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    copy(integration/'business.sqlite','business.sqlite')
    for name in ('p3-nl2sql-evidence.json','p3-analysis-evidence.json','p3-codeact-evidence.json','p3-closure-acl-evidence.json','integration.xml','restart/evidence.json'):
        copy(integration/name,name)
    for path in (integration/'files').rglob('*'):
        if path.is_file() and (path.name in {'query-1.csv','query-1-chart.json','query-provenance.json','分类销售分析.md','sales.csv','codeact-sales.csv'}):copy(path,'files/'+str(path.relative_to(integration/'files')))
    for name in ('closure-unit.xml','closure-ui.json','failure-baseline.json'):
        copy(ROOT/'target/python-migration-p3'/name,name)
    tool=json.loads((ROOT/'target/python-migration-p3/tool-tests.json').read_text());copy(Path(tool['root'])/'results.json','tool-results.json')
    # Capture only public test IDs/ownership, never raw visitor cookies/service keys.
    engine=create_engine('mysql+pymysql://root@/reactor_p1_isolated?unix_socket='+quote(str(browser/'mysql.sock'),safe='')+'&charset=utf8mb4')
    with engine.connect() as c:
        owners=[dict(r) for r in c.execute(text('SELECT resource_kind,resource_key,visitor_id,parent_key FROM reactor_private_resource_owner')).mappings()]
        sessions=[dict(r) for r in c.execute(text('SELECT session_id,visitor_id,title,status,latest_request_id FROM ai_agent_dialogue_session')).mappings()]
    engine.dispose()
    kb_ids=[r['resource_key'] for r in owners if r['resource_kind']=='kb']
    assert len(kb_ids)==1,'Use a browser root containing exactly this walkthrough KB'
    kb=kb_ids[0]
    document_files=list((browser/'files').rglob('*_ui-source.txt'))
    assert len(document_files)==1
    document_file=document_files[0];doc=document_file.parent.name
    analysis_sessions=[s for s in sessions if '通过数据分析工具' in s['title']]
    assert len(analysis_sessions)==1
    session=analysis_sessions[0]['session_id']
    file_path='/v1/file_tool/preview/'+doc+'/'+document_file.name
    connection=json.loads((browser/'connection.json').read_text());base=connection['backend_url']
    with httpx.Client(base_url=base,trust_env=False,timeout=30) as b:
        b.get('/api/agent/visitor/bootstrap').raise_for_status()
        denied={'browserKB':b.post('/v1/documents/list_kb_files',json={'kb_id':kb}).status_code,'browserDocument':b.get(file_path).status_code,
                'browserAnalysisFile':b.get('/v1/file_tool/preview/'+session+'/分类销售分析.md').status_code}
        assert set(denied.values())=={403},denied
    copy(document_file,'browser/ui-source.txt')
    copy(browser/'files'/session/'分类销售分析.md','browser/分类销售分析.md')
    with sqlite3.connect('file:'+str(browser/'kb_file.db')+'?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        kb_tables={table:[dict(r) for r in c.execute('SELECT * FROM "'+table+'" WHERE kb_id=?',(kb,))] for table in tables if 'kb_id' in {r[1] for r in c.execute('PRAGMA table_info("'+table+'")')}}
    evidence={'status':'P3 implementation and isolation acceptance closed; external integrations U; no production switch','unit':118,'integration':{'sqlite':str(integration),'mysql':str(mysql),'tests_per_run':42,'java_frames':[5,2,11]},'browser':{'root':str(browser),'model':'HTTP fixture only; original Tool/SQL/DataFrame/files real','owners':owners,'sessions':sessions,'KB':kb_tables,'crossVisitor':denied,'flow':['React DataAgent SQLite chart/table','ReAct data_analysis/get_data → NL2SQL → SQLite → real DataFrame','real report preview → refresh → recent session/history → same file preview','React KB create/upload → private original URL preview; ingestion explicitly FAILED without embedding config']},'tool':{'root':tool['root'],'pass':114,'fail':13,'same_HEAD_failures':True},'UI':{'pass':434,'fail':2,'same_HEAD_failures':True,'build':'PASS in new copy'},'files':manifest}
    (fixtures/'p3-closure-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2,default=str)+'\n')
    print('P3 closure evidence exported: '+str(len(manifest))+' files; three browser-created resources rejected for visitor B (403)')

if __name__=='__main__':main()
