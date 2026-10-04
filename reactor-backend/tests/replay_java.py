#!/usr/bin/env python3
"""Original Java replay over isolated Python-written ledger facts; no DB/HTTP boot."""
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/python_migration'))
from run_baseline import classpath


def verify(root):
    root=Path(root)
    assert (root/'ISOLATED_P1').is_file()
    cp,_=classpath()
    classes=ROOT/'target/python-migration-p1/java'
    classes.mkdir(parents=True,exist_ok=True)
    subprocess.run(['javac','-encoding','UTF-8','-cp',cp,'-d',str(classes),str(Path(__file__).with_name('ReplayP1.java'))],check=True)
    compare_case(root,cp,classes,'facts.json','python-replay.json','java-replay.json')
    for prefix in ('genui','rich'):
        if (root/(prefix+'-facts.json')).exists():
            compare_case(root,cp,classes,prefix+'-facts.json',prefix+'-python-replay.json',prefix+'-java-replay.json')

def compare_case(root,cp,classes,facts,python_frames,java_frames):
    subprocess.run(['java','-Duser.timezone=Asia/Shanghai','-cp',str(classes)+':'+cp,'ReplayP1',str(root/facts),str(root/java_frames)],check=True)
    outputs=[json.loads((root/name).read_text()) for name in (python_frames,java_frames)]
    for output in outputs:
        for f in output: f['resultMap']['eventData']['taskId']='dynamic-task'
    if outputs[0]!=outputs[1]:
        from compare import compare
        raise AssertionError('\n'.join(compare(outputs[1],outputs[0])[:30]))
    print('Original Java replay of actual Python-written MySQL rows: PASS ('+str(len(outputs[0]))+' frames)')

if __name__=='__main__': verify(sys.argv[1])
