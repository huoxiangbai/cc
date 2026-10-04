"""Original Java producer and isolated memory behavior baseline."""
from pathlib import Path
import subprocess
from replay_java import ROOT,classpath


def capture(root):
    cp,agent=classpath();classes=ROOT/'target/python-migration-p4/java';classes.mkdir(parents=True,exist_ok=True)
    subprocess.run(['javac','-proc:none','-encoding','UTF-8','-cp',cp,'-d',str(classes),str(Path(__file__).with_name('MemoryP4.java'))],check=True)
    tests=['WorkingMemoryCompactorTest','MemoryContextFenceTest','LtmForkParityTest','SessionContextCompactionOutcomeTest','CuratedMemoryStoreTest','WorkingMemorySessionSearchServiceTest','SubAgentLtmIsolationTest']
    with (root/'java-memory-tests.log').open('w') as log:
        subprocess.run(['java',f'-javaagent:{agent}',f'-Djava.io.tmpdir={root}','-Duser.timezone=Asia/Shanghai','-cp',str(classes)+':'+cp,'MemoryP4',str(root/'java-memory.json'),*['org.wwz.ai.test.domain.'+t for t in tests]],cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
