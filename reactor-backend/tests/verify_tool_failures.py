"""Re-run the five failed original files against Git HEAD sources in NEW temp roots."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from run_tool_tests import ROOT,SCRIPT

FILES=['test_code_interpreter_permissions.py','test_code_interpreter_runtime_guard.py','test_e2b_sandbox_backend.py','test_mrag_api.py','test_mrag_document_processor.py']


def main():
    root=Path(tempfile.mkdtemp(prefix='reactor-p3-failure-baseline-'))
    paths=subprocess.check_output(['git','ls-tree','-r','--name-only','HEAD','reactor-tool/reactor_tool'],cwd=ROOT,text=True).splitlines()
    for name in paths:
        if Path(name).suffix not in {'.py','.json','.txt','.md'}:continue
        target=root/'baseline'/Path(name).relative_to('reactor-tool')
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(subprocess.check_output(['git','show','HEAD:'+name],cwd=ROOT))
    latest=json.loads((ROOT/'target/python-migration-p3/tool-tests.json').read_text())
    actual={r['file']:r for r in latest['results']};out=[]
    def failures(path):
        return sorted(t.attrib.get('classname','')+'::'+t.attrib['name'] for t in ET.parse(path).iter('testcase') if t.find('failure') is not None or t.find('error') is not None)
    for name in FILES:
        work=root/name.removesuffix('.py');work.mkdir()
        env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','TMPDIR')}
        env.update(PYTHONPATH=str(root/'baseline'),SQLITE_DB_PATH=str(work/'files.db'),SQLITE_PATH=str(work/'mrag.db'),
                   FILE_SAVE_PATH=str(work/'files'),FILE_SERVER_URL='http://127.0.0.1:1/v1/file_tool',CODE_SANDBOX_BACKEND='local',
                   TEXT_EMBEDDING_DIMENSION='3',IMAGE_EMBEDDING_DIMENSION='3',VECTOR_STORE_TYPE='qdrant',TEXT_COLLECTION='p3-text',
                   IMAGE_COLLECTION='p3-image',PAGE_COLLECTION='p3-page',HF_HUB_OFFLINE='1',AWS_EC2_METADATA_DISABLED='true',STORE_TYPE='sqlite',
                   LITELLM_LOCAL_MODEL_COST_MAP='True',CRAWL4_AI_BASE_DIRECTORY=str(work/'crawl-cache'))
        with (work/'baseline.log').open('w') as log:
            r=subprocess.run([sys.executable,'-c',SCRIPT,str(ROOT/'reactor-tool/tests'/name),'-q','--junitxml='+str(work/'baseline.xml')],cwd=work,env=env,stdout=log,stderr=subprocess.STDOUT)
        before=failures(work/'baseline.xml');after=failures(actual[name]['junit'])
        out.append({'file':name,'baseline_exit':r.returncode,'baseline_failed':before,'current_failed':after,'same_failures':before==after,'baseline_log':str(work/'baseline.log'),'current_log':actual[name]['log']})
        print(name+': identical failures='+str(before==after),flush=True)
    dest=ROOT/'target/python-migration-p3/failure-baseline.json';dest.write_text(json.dumps({'root':str(root),'results':out},indent=2))
    print('Baseline evidence: '+str(root))
    return int(not all(r['same_failures'] for r in out))

if __name__=='__main__':raise SystemExit(main())
