"""Real operator CLI and HTTP import against ONLY new local library roots."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from functools import partial

ROOT=Path(__file__).resolve().parents[2]

def main():
    root=Path(tempfile.mkdtemp(prefix='reactor-p4-skill-admin-'))
    source=ROOT/'docs/python-migration/fixtures/p4-artifacts/p4-created.skill'
    shutil.copy2(source,root/'package.skill')
    env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','TMPDIR')}
    env['PYTHONPATH']=str(ROOT/'reactor-backend')
    def run(library,*args,ok=True):
        result=subprocess.run([sys.executable,'-m','reactor_backend.skills.manage','--root',str(root/library),'--authorized-root',*args],cwd=root,env=env,capture_output=True,text=True,timeout=10)
        assert (result.returncode==0)==ok,result.stderr
        return json.loads(result.stdout) if ok else None
    imported=run('library','import-package','--file',str(root/'package.skill'))
    assert imported['name']=='p4-created'
    assert run('library','reload')[0]['name']=='p4-created'
    assert run('library','preview','--file',str(root/'package.skill'))['nameTaken']
    run('library','import-package','--file',str(root/'package.skill'),ok=False)
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(root)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        downloaded=run('downloaded','import-url','--url',f'http://127.0.0.1:{server.server_port}/package.skill')
        assert downloaded['name']=='p4-created'
        assert (root/'downloaded/p4-created/SKILL.md').read_bytes()==(root/'library/p4-created/SKILL.md').read_bytes()
    finally:server.shutdown();server.server_close();thread.join(timeout=5)
    evidence=dict(root=str(root),operator_cli='PASS',package_import='PASS',reload='PASS',duplicate_rejected='PASS',real_http_import='PASS',production_library_touched=False)
    (root/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence))

if __name__=='__main__':main()
