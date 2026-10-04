import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from compare import normalize, compare, assert_partial_order
from audit_copy import inside, ddl_snapshot, sqlite_snapshot, check_files

ROOT=Path(__file__).resolve().parents[2]
FIXTURES=ROOT/'docs/python-migration/fixtures'

class ComparisonTests(unittest.TestCase):
    def test_fields_types_and_order_are_not_discarded(self):
        self.assertTrue(compare({'id':1,'data':None},{'id':'1'}))
        self.assertTrue(compare([1,2],[2,1]))
        self.assertTrue(compare(normalize({'id':1},['/id']),normalize({'id':'1'},['/id'])))
        self.assertFalse(compare({'a':None,'b':1},{'b':1,'a':None}))
    def test_dynamic_ids_preserve_association(self):
        left={'id':'a','ref':'a'}; right={'id':'b','ref':'b'}
        self.assertFalse(compare(normalize(left,['/id','/ref']),normalize(right,['/id','/ref'])))
        self.assertTrue(compare(normalize(left,['/id','/ref']),normalize({'id':'b','ref':'c'},['/id','/ref'])))
    def test_required_order_detects_missing_or_reversed_events(self):
        assert_partial_order([{'key':'call'},{'key':'other'},{'key':'result'}],[('call','result')])
        for events in ([{'key':'call'}],[{'key':'result'},{'key':'call'}]):
            with self.assertRaises(AssertionError):assert_partial_order(events,[('call','result')])
    def test_java_wire_has_no_named_events_and_preserves_utf8(self):
        fixture=json.loads((FIXTURES/'java-behavior.json').read_text())
        wire=fixture['http']['query-sse']['body']
        self.assertNotIn('event:',wire);self.assertNotIn('[DONE]',wire)
        frames=[json.loads(line[5:]) for line in wire.splitlines() if line.startswith('data:')]
        self.assertEqual(['heartbeat','follow_pending','follow_idle'],[f['packageType'] for f in frames])
        self.assertEqual([False,False,True],[f['finished'] for f in frames]);self.assertEqual(800,frames[1]['retryMs'])
    def test_every_route_has_runtime_mapping(self):
        source=json.loads((FIXTURES/'source-contracts.json').read_text())['javaRoutes']
        runtime=json.loads((FIXTURES/'runtime-routes.json').read_text())
        self.assertEqual(108,len(runtime))
        pairs={(verb,path) for row in runtime for path in row['paths'] for verb in row['verbs'] or ['任意（未限定）']}
        self.assertEqual({(r['verb'],r['path']) for r in source},pairs)
    def test_tool_schema_coverage(self):
        capture=json.loads((FIXTURES/'tool-schemas.json').read_text())
        for name in set(capture['factoryReact']+capture['factoryPlanSolve']+capture['planMain']+capture['dataAgent']):
            self.assertIn(name,capture['schemas'])
            self.assertIsInstance(capture['schemas'][name]['parameters'],dict)
        self.assertIn('TaskOutput',capture['planMainConfigured']);self.assertIn('SendMessage',capture['planMainConfigured'])

class CopyAuditTests(unittest.TestCase):
    def test_ddl_detects_semantic_drift(self):
        ddl=(ROOT/'Reactor-agent-app/src/main/resources/db/schema.sql').read_text()
        self.assertEqual(33,len(ddl_snapshot(ddl)))
        self.assertTrue(compare(ddl_snapshot(ddl),ddl_snapshot(ddl.replace('VARCHAR(64)','VARCHAR(65)',1))))
    def test_readonly_sqlite_and_file_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);db=root/'copy.db'
            with sqlite3.connect(db) as conn:conn.execute('CREATE TABLE fileinfo(id INTEGER PRIMARY KEY, file_id TEXT)')
            before=hashlib.sha256(db.read_bytes()).hexdigest()
            self.assertEqual('ok',sqlite_snapshot(db)['integrity'])
            self.assertEqual(before,hashlib.sha256(db.read_bytes()).hexdigest())
            target=root/'中文.txt';target.write_text('fixture')
            row={'artifactId':1,'fileId':'file-1','requestId':'req-1','storageKey':'中文.txt','relativePath':'中文.txt',
                 'fileSize':target.stat().st_size,'fileHash':hashlib.md5(target.read_bytes()).hexdigest(),'previewUrl':'/preview','downloadUrl':'/download'}
            self.assertFalse(check_files(root,[row])['errors'])
            row['fileSize']=0;self.assertTrue(check_files(root,[row])['errors'])
    def test_traversal_absolute_outside_and_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'ok').write_text('x');(root/'link').symlink_to(root/'ok')
            self.assertEqual(root.resolve()/'ok',inside(root,'ok'))
            for name in ('link','/etc/hosts','../'):
                with self.assertRaises(ValueError):inside(root,name)

if __name__=='__main__':unittest.main()
