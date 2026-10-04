#!/usr/bin/env python3
"""Run P1 against an ALWAYS NEW local MySQL datadir and original Tool routers.
Never reads .env or connects to an existing MySQL URL. --serve retains isolated
processes for an original React browser walkthrough until Ctrl-C.
"""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import secrets
import sqlite3
import time
from urllib.parse import quote
import httpx
import pymysql

ROOT=Path(__file__).resolve().parents[2]
PY=ROOT/'reactor-backend/.venv/bin/python'


def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));return s.getsockname()[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=['p1','p2','p3','p4','p5'],default='p1')
    parser.add_argument('--business-db',choices=['mysql','sqlite'],default='sqlite')
    parser.add_argument('--serve',action='store_true')
    parser.add_argument('--live-model',action='store_true',help='Explicitly use inherited REACTOR_MODEL_* with isolated DB/tools')
    args=parser.parse_args()
    isolation=Path(tempfile.mkdtemp(prefix='reactor-'+args.phase+'-'))
    (isolation/'ISOLATED_P1').write_text('created by integration.py; no old data\n')
    processes=[]
    base_env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','TMPDIR','SYSTEMROOT')}
    base_env.update(PYTHONPATH=os.pathsep.join(map(str,[ROOT/'reactor-backend/tests',ROOT/'reactor-tool',ROOT/'reactor-backend'])),PYTHONUNBUFFERED='1',NO_PROXY='127.0.0.1,localhost,::1')
    def start(command,name,env=None):
        log=(isolation/(name+'.log')).open('w')
        p=subprocess.Popen(command,cwd=isolation,env=env or base_env,stdout=log,stderr=subprocess.STDOUT)
        processes.append((p,log));return p
    try:
        init=subprocess.run(['mysqld','--no-defaults','--initialize-insecure',f'--datadir={isolation}/mysql',f'--log-error={isolation}/mysql-init.log'],env=base_env,cwd=isolation)
        if init.returncode: raise RuntimeError('MySQL initialize failed; see '+str(isolation))
        mysql=start(['mysqld','--no-defaults',f'--datadir={isolation}/mysql',f'--socket={isolation}/mysql.sock',f'--pid-file={isolation}/mysql.pid',
                    '--skip-networking','--mysqlx=0',f'--log-error={isolation}/mysql-server.log'],'mysql-process')
        for _ in range(100):
            try:
                connection=pymysql.connect(unix_socket=str(isolation/'mysql.sock'),user='root',charset='utf8mb4',autocommit=True)
                break
            except pymysql.MySQLError:
                if mysql.poll() is not None: raise RuntimeError('Isolated MySQL exited; inspect '+str(isolation))
                time.sleep(.1)
        else: raise RuntimeError('Isolated MySQL readiness timeout')
        with connection:
            with connection.cursor() as c:
                c.execute('CREATE DATABASE reactor_p1_isolated CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
                c.execute('USE reactor_p1_isolated')
                # Extract only CREATE TABLE statements. Never executes old DROP/seed scripts.
                sql=(ROOT/'Reactor-agent-app/src/main/resources/db/schema.sql').read_text()
                statements=re.findall(r'CREATE TABLE IF NOT EXISTS.*?ENGINE=.*?;',sql,re.S)
                assert len(statements)==33
                for statement in statements: c.execute(statement)
                acl=(ROOT/'reactor-backend/migrations/001_private_resource_acl.sql').read_text().split('CREATE TABLE',1)[1]
                c.execute('CREATE TABLE'+acl)
                for name in ('002_admin_session.sql','003_featured_resource.sql'):
                    c.execute((ROOT/'reactor-backend/reactor_backend/resources/migrations'/name).read_text())
        if args.phase in ('p3','p4','p5'):
            if args.business_db=='mysql':
                with pymysql.connect(unix_socket=str(isolation/'mysql.sock'),user='root',autocommit=True) as c:
                    with c.cursor() as cursor:
                        cursor.execute('CREATE DATABASE reactor_p3_business CHARACTER SET utf8mb4')
                        cursor.execute('CREATE TABLE reactor_p3_business.sales (category VARCHAR(20), amount DECIMAL(12,4))')
                        cursor.execute("INSERT INTO reactor_p3_business.sales VALUES ('A',10),('A',20),('B',7.5)")
                db={'type':'mysql','url':'mysql+pymysql://root@/reactor_p3_business?unix_socket='+quote(str(isolation/'mysql.sock'),safe='')+'&charset=utf8mb4'}
            else:
                with sqlite3.connect(isolation/'business.sqlite') as c:
                    c.execute('CREATE TABLE sales(category TEXT, amount DECIMAL_TEXT)')
                    c.executemany('INSERT INTO sales VALUES (?,?)',[('A','10.0000'),('A','20.0000'),('B','7.5000')])
                db={'type':'sqlite','path':str(isolation/'business.sqlite')}
            config={'db':db,'es':{'enable':False},'qdrant':{'enable':False},'modelList':[{'id':'sales-model','type':'TABLE','name':'分类销售','content':'sales','defaultRecallFields':'category','analyzeSuggestFields':'category'}]}
            (isolation/'data-config.json').write_text(json.dumps(config))
        tool_port,model_port,backend_port=port(),port(),port()
        if args.phase=='p4':
            from p4_java import capture
            capture(isolation)
            import shutil
            shutil.copytree(ROOT/'runtime/skills/skill-creator',isolation/'skills/skill-creator',ignore=shutil.ignore_patterns('__pycache__','.DS_Store'))
            with pymysql.connect(unix_socket=str(isolation/'mysql.sock'),user='root',database='reactor_p1_isolated',autocommit=True) as c:
                with c.cursor() as cursor:
                    for kind in ('sse','stdio','streamable_http'):
                        mcp_port=port()
                        if kind=='stdio':config={'stdio':{'P4_'+kind:{'command':str(PY),'args':[str(ROOT/'reactor-backend/tests/p4_mcp_endpoint.py'),'--transport','stdio']}}}
                        else:
                            start([str(PY),str(ROOT/'reactor-backend/tests/p4_mcp_endpoint.py'),'--transport','streamable-http' if kind=='streamable_http' else 'sse','--port',str(mcp_port)],'mcp-'+kind)
                            config={'baseUri':f'http://127.0.0.1:{mcp_port}','sseEndpoint':'/sse','endpoint':'/mcp'}
                        cursor.execute('INSERT INTO ai_client_tool_mcp (mcp_id,mcp_name,transport_type,transport_config,request_timeout,status) VALUES (%s,%s,%s,%s,1,1)',('p4-'+kind,'P4_'+kind,kind,json.dumps(config)))
            (isolation/'memory-config.json').write_text(json.dumps({'providers':['builtin','holographic','openviking'],'review_enabled':True,'review_interval':1,'fork_timeout_seconds':5}))
        if args.phase=='p5':
            import shutil
            shutil.copytree(ROOT/'runtime/skills/skill-creator',isolation/'skills/skill-creator',ignore=shutil.ignore_patterns('__pycache__','.DS_Store'))
            image_port=port()
            start([str(PY),'-m','uvicorn','p5_model_service:app','--host','127.0.0.1','--port',str(image_port)],'p5-image-provider')
            (isolation/'image-config.json').write_text(json.dumps({'base_url':f'http://127.0.0.1:{image_port}','api_key':'p5-image-test-only'}))
        tool_url=f'http://127.0.0.1:{tool_port}'
        service_token=secrets.token_hex(32)
        public_tool_url=f'http://127.0.0.1:{backend_port}'
        env={**base_env,'SQLITE_DB_PATH':str(isolation/'autobots.db'),'SQLITE_PATH':str(isolation/'kb_file.db'),
             'FILE_SAVE_PATH':str(isolation/'files'),'FILE_SERVER_URL':public_tool_url+'/v1/file_tool',
             'FILE_SERVER_INTERNAL_URL':tool_url+'/v1/file_tool','REACTOR_DOCGEN_HOME':str(isolation/'docgen'),
             'REACTOR_DOCGEN_OUTPUT_DIR':str(isolation/'output'),'REACTOR_WORKSPACE_ROOT':str(isolation/'workspace'),'STORE_TYPE':'sqlite',
             'REACTOR_TOOL_SERVICE_TOKEN':service_token,'REACTOR_TOOL_AUTH_REQUIRED':'true'}
        if args.phase in ('p3','p4','p5'):env.update(REACTOR_TEST_PHASE='p3',CODE_SANDBOX_BACKEND='local',
            OPENAI_BASE_URL=f'http://127.0.0.1:{model_port}/v1',OPENAI_API_KEY='p3-isolation-model-key',CODE_INTERPRETER_MODEL='p3-fixture',
            DEFAULT_MODEL='p3-fixture',NL2SQL_MODEL_NAME='p3-fixture',REWRITE_MODEL_NAME='p3-fixture',THINK_MODEL_NAME='p3-fixture',
            TR_TABLE_FILTER_MODEL_NAME='p3-fixture',TR_COLUMN_FILTER_MODEL_NAME='p3-fixture',TEXT_EMBEDDING_DIMENSION='3',IMAGE_EMBEDDING_DIMENSION='3',
            TEXT_COLLECTION='p3-text',IMAGE_COLLECTION='p3-image',PAGE_COLLECTION='p3-page',VECTOR_STORE_TYPE='qdrant',
            ANA_SCHEMA_URL=f'http://127.0.0.1:{backend_port}/data/queryModelInfo',ANA_DATA_URL=f'http://127.0.0.1:{backend_port}/data/apiChatQuery',
            HF_HUB_OFFLINE='1',AWS_EC2_METADATA_DISABLED='true',LITELLM_LOCAL_MODEL_COST_MAP='True',CRAWL4_AI_BASE_DIRECTORY=str(isolation/'crawl-cache'),
            CODE_INTERPRETER_ENABLE_PRE_EXECUTION_VALIDATION='true',CODE_INTERPRETER_ENABLE_PATH_SANDBOX='true',CODE_INTERPRETER_ENABLE_RUNTIME_DOUBLE_CHECK='true')
        tool=start([str(PY),'-m','uvicorn','tool_service:app','--host','127.0.0.1','--port',str(tool_port)],'tool',env)
        if args.live_model:
            model_env={k:os.environ[k] for k in ('REACTOR_MODEL_BASE_URL','REACTOR_MODEL_NAME','REACTOR_MODEL_API_KEY') if os.environ.get(k)}
            if not all(model_env.get(k) for k in ('REACTOR_MODEL_BASE_URL','REACTOR_MODEL_NAME','REACTOR_MODEL_API_KEY')):
                raise RuntimeError('--live-model requires three explicit REACTOR_MODEL_* variables; never discovers credentials')
        else:
            start([str(PY),'-m','uvicorn',('p5_model_service:app' if args.phase=='p5' else 'p4_model_service:app' if args.phase=='p4' else 'p3_model_service:app' if args.phase=='p3' else 'p2_model_service:app' if args.phase=='p2' else 'model_service:app'),'--host','127.0.0.1','--port',str(model_port)],'fixed-upstream',{**base_env,'P5_PUBLIC_TOOL_URL':public_tool_url})
            model_env={'REACTOR_MODEL_BASE_URL':f'http://127.0.0.1:{model_port}','REACTOR_MODEL_NAME':'p1-fixed-upstream','REACTOR_MODEL_API_KEY':'isolation-test-key'}
        url='mysql+pymysql://root@/reactor_p1_isolated?unix_socket='+quote(str(isolation/'mysql.sock'),safe='')+'&charset=utf8mb4'
        backend_env={**base_env,**model_env,'REACTOR_MYSQL_URL':url,'REACTOR_TOOL_URL':tool_url,
                     'REACTOR_WORKSPACE_ROOT':str(isolation/'workspace'),'REACTOR_COOKIE_SECURE':'false',
                     'REACTOR_TOOL_SERVICE_TOKEN':service_token,'REACTOR_BACKEND_PORT':str(backend_port),'REACTOR_RECOVER_EXCLUSIVE':'true'}
        if args.phase in ('p3','p4','p5'):backend_env.update(REACTOR_DATA_CONFIG_FILE=str(isolation/'data-config.json'),REACTOR_ANALYSIS_MODELS='sales-model')
        if args.phase=='p4':backend_env.update(REACTOR_SKILL_ROOT=str(isolation/'skills'),REACTOR_SKILL_SCOPE_POLICY='session-copy',REACTOR_MEMORY_CONFIG_FILE=str(isolation/'memory-config.json'))
        if args.phase=='p5':backend_env.update(REACTOR_IMAGE_CONFIG_FILE=str(isolation/'image-config.json'),REACTOR_SKILL_ROOT=str(isolation/'skills'))
        # Protected backend verifies Tool authentication at startup. Wait for original
        # Tool imports before starting it; never bypass that security check.
        for _ in range(600):
            try:
                r=httpx.get(tool_url+'/_reactor/security',headers={'X-Reactor-Service-Token':service_token},timeout=1,trust_env=False)
                if r.status_code==200 and r.json().get('internal_auth'):break
            except httpx.HTTPError:pass
            if tool.poll() is not None:raise RuntimeError('Original Tool startup failed: '+str(isolation))
            time.sleep(.1)
        else:raise RuntimeError('Original Tool readiness timeout')
        backend=start([str(PY),'-m','reactor_backend'],'backend',backend_env)
        base=f'http://127.0.0.1:{backend_port}'
        for _ in range(600):
            try:
                if httpx.get(base+'/web/health',timeout=1,trust_env=False).status_code==200 and httpx.get(tool_url+'/docs',timeout=1,trust_env=False).status_code==200: break
            except httpx.HTTPError: pass
            if backend.poll() is not None or tool.poll() is not None:
                raise RuntimeError('Isolated service failed; logs: '+str(isolation))
            time.sleep(.1)
        else: raise RuntimeError('Service readiness timeout; '+str(isolation))
        evidence={'phase':args.phase,'isolation_root':str(isolation),'backend_url':base,'tool_url':tool_url,'model':'live-unverified-until-run' if args.live_model else 'fixed-upstream-test-only',
                  'mysql':'9.x local new datadir; Unix socket only','schema_tables':33,'business_db':args.business_db if args.phase in ('p3','p4','p5') else None,'public_tool_url':public_tool_url}
        (isolation/'connection.json').write_text(json.dumps(evidence,indent=2)+'\n')
        print(json.dumps(evidence),flush=True)
        if args.serve:
            print('Original UI connection: SERVICE_BASE_URL='+base+' REACTOR_TOOL_BASE_URL='+public_tool_url+' npm run dev',flush=True)
            while True: time.sleep(1)
        else:
            test_env={**base_env,'P1_TEST_ROOT':str(isolation),'P1_TEST_MYSQL_URL':url,'P1_TEST_BACKEND_URL':base,'P1_TEST_TOOL_URL':tool_url,'P1_TEST_MODEL_URL':f'http://127.0.0.1:{model_port}','P1_TEST_SERVICE_TOKEN':service_token,'P3_BUSINESS_DB':args.business_db,**({'P5_TEST_IMAGE_URL':f'http://127.0.0.1:{image_port}'} if args.phase=='p5' else {})}
            test_file='test_live.py' if args.live_model else 'test_integration.py'
            result=subprocess.run([str(PY),'-m','pytest',str(ROOT/'reactor-backend/tests'/test_file),*([str(ROOT/'reactor-backend/tests/test_p2_integration.py'),str(ROOT/'reactor-backend/tests/test_p2_recovery.py')] if args.phase in ('p2','p3','p4','p5') and not args.live_model else []),*([str(ROOT/'reactor-backend/tests/test_p3_integration.py'),str(ROOT/'reactor-backend/tests/test_p3_closure_integration.py')] if args.phase in ('p3','p4','p5') and not args.live_model else []),*([str(ROOT/'reactor-backend/tests/test_p5_integration.py')] if args.phase=='p5' and not args.live_model else []),*([str(ROOT/'reactor-backend/tests/test_p4_integration.py')] if args.phase=='p4' and not args.live_model else []),'-q','--junitxml='+str(isolation/'integration.xml')],cwd=ROOT/'reactor-backend',env=test_env)
            if result.returncode == 0 and not args.live_model:
                from replay_java import verify
                verify(isolation)
                evidence['java_replay']='PASS: actual Python-written MySQL rows'
            evidence['exit_code']=result.returncode
            output=ROOT/('target/python-migration-'+args.phase+'/latest-integration.json')
            output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(json.dumps(evidence,indent=2)+'\n')
            raise SystemExit(result.returncode)
    finally:
        for p,log in reversed(processes):
            if p.poll() is None:
                p.terminate()
                try: p.wait(timeout=15)
                except subprocess.TimeoutExpired: p.kill();p.wait(timeout=5)
            log.close()
        print('Isolated logs/data preserved: '+str(isolation),flush=True)

if __name__ == '__main__': main()
