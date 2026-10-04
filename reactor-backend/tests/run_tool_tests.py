#!/usr/bin/env python3
"""Original Tool behavior tests, each in a fresh isolated environment; no .env/external sockets."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
FILES=['test_social_tools.py','test_deepsearch_engine_selection.py','test_deepsearch_llm_config.py',
       'test_web_fetcher.py','test_web_fetch_api.py','test_code_interpreter_api.py','test_code_interpreter_outputs.py',
       'test_code_interpreter_permissions.py','test_code_interpreter_runtime_guard.py','test_python_sandbox_executor.py',
       'test_sandbox_backend_config.py','test_e2b_sandbox_backend.py','test_mrag_api.py','test_mrag_history_routes.py',
       'test_mrag_history_persistence.py','test_mrag_document_routes.py','test_mrag_document_processor.py',
       'test_mrag_kb_doc_store.py','test_mrag_splitter.py','test_mrag_query_processor.py','test_sop_workspace.py',
       'test_plan_sop.py','test_data_clean.py','test_analysis_data_guard.py']
SCRIPT='''
import dotenv,dotenv.main,sys,os
from pathlib import Path
no=lambda *a,**k:''
dotenv.find_dotenv=dotenv.main.find_dotenv=no
def guard(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)) and Path(os.fsdecode(args[0])).name=='.env':raise RuntimeError('No .env reads in Tool tests')
 if event=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ('127.0.0.1','::1','localhost'):raise RuntimeError('External network forbidden in isolated Tool tests')
sys.addaudithook(guard)
import pytest
raise SystemExit(pytest.main(sys.argv[1:]))
'''

def main():
    root=Path(tempfile.mkdtemp(prefix='reactor-p3-tool-tests-'));results=[]
    for filename in FILES:
        work=root/filename.removesuffix('.py');work.mkdir()
        env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','TMPDIR')}
        env.update(PYTHONPATH=str(ROOT/'reactor-tool'),SQLITE_DB_PATH=str(work/'files.db'),SQLITE_PATH=str(work/'mrag.db'),
                   FILE_SAVE_PATH=str(work/'files'),FILE_SERVER_URL='http://127.0.0.1:1/v1/file_tool',CODE_SANDBOX_BACKEND='local',
                   TEXT_EMBEDDING_DIMENSION='3',IMAGE_EMBEDDING_DIMENSION='3',VECTOR_STORE_TYPE='qdrant',TEXT_COLLECTION='p3-text',
                   IMAGE_COLLECTION='p3-image',PAGE_COLLECTION='p3-page',HF_HUB_OFFLINE='1',AWS_EC2_METADATA_DISABLED='true',STORE_TYPE='sqlite',
                   LITELLM_LOCAL_MODEL_COST_MAP='True',CRAWL4_AI_BASE_DIRECTORY=str(work/'crawl-cache'))
        with (work/'test.log').open('w') as log:
            r=subprocess.run([sys.executable,'-c',SCRIPT,str(ROOT/'reactor-tool/tests'/filename),'-q','--junitxml='+str(work/'result.xml')],env=env,cwd=work,stdout=log,stderr=subprocess.STDOUT)
        results.append({'file':filename,'exit_code':r.returncode,'log':str(work/'test.log'),'junit':str(work/'result.xml')})
        print(filename+': '+str(r.returncode),flush=True)
    (root/'results.json').write_text(json.dumps(results,indent=2))
    out=ROOT/'target/python-migration-p3/tool-tests.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({'root':str(root),'results':results},indent=2))
    print('Original Tool isolated evidence: '+str(root))
    return int(any(r['exit_code'] for r in results))

if __name__=='__main__':raise SystemExit(main())
