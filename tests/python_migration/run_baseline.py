#!/usr/bin/env python3
"""Offline P0 capture/check; never loads application profiles or environment files."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'docs/python-migration/fixtures'
TESTS = [
 'org.wwz.ai.test.domain.ActiveAgentRunRegistryTest',
 'org.wwz.ai.test.domain.LlmRequestRetryTest',
 'org.wwz.ai.test.domain.LlmModelFallbackTest',
 'org.wwz.ai.test.domain.tasklist.SendMessageMailboxTest',
 'org.wwz.ai.test.domain.DeferredMcpCatalogTest',
 'org.wwz.ai.test.domain.canvas.GenUiExportServiceTest',
 'org.wwz.ai.test.domain.canvas.GenUiSchemaTest',
 'org.wwz.ai.test.domain.planmode.PlanModeToolsTest',
 'org.wwz.ai.test.domain.subagent.SubAgentConcurrencyHardeningTest',
 'org.wwz.ai.test.domain.subagent.SubAgentResumeHardeningTest',
 'org.wwz.ai.test.stream.BackgroundStreamSettleTest',
 'org.wwz.ai.test.domain.AgentResponseHandlerReplayContractTest',
 'org.wwz.ai.test.domain.SseEmitterAgentSessionStreamTest',
 'org.wwz.ai.test.domain.ConversationHistoryControllerTest',
 'org.wwz.ai.test.domain.VisitorIdentityFilterTest',
 'org.wwz.ai.test.domain.ConversationSessionOwnershipApplicationServiceTest',
 'org.wwz.ai.test.application.agent.planmode.PlanApprovalResumeApplicationServiceTest',
 'org.wwz.ai.application.agent.subagent.SubAgentDefinitionAdminApplicationServiceTest',
 'org.wwz.ai.test.spring.ai.AgentToolCollectionFactoryTest',
 'org.wwz.ai.test.domain.ReactorMapperNamespaceBindingTest',
 'org.wwz.ai.test.domain.ToolLlmObservationRuntimeTest',
 'org.wwz.ai.test.domain.ToolArtifactBindingRuntimeTest',
]


def run(cmd, log, **kw):
    with log.open('ab') as out:
        result = subprocess.run(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, **kw)
    if result.returncode:
        raise SystemExit(f'Failed ({result.returncode}); inspect {log}')


def classpath():
    reports = ROOT / 'Reactor-agent-app/target/surefire-reports'
    report = reports / 'TEST-org.wwz.ai.test.domain.SseEmitterAgentSessionStreamTest.xml'
    props = {p.get('name'): p.get('value') for p in ET.parse(report).find('properties')}
    paths = props['java.class.path'].split(os.pathsep)
    for module in ROOT.glob('Reactor-agent-*'):
        for directory in ('target/test-classes', 'target/classes'):
            if (module / directory).exists():
                paths.insert(0, str(module / directory))
    paths = list(dict.fromkeys(paths))
    if any(not Path(p).exists() for p in paths):
        raise SystemExit('Incomplete Maven cache; compile the reactor before capture')
    return os.pathsep.join(paths), next(p for p in paths if '/mockito-core/' in p and p.endswith('.jar'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', action='store_true', help='Explicitly replace reviewed golden fixtures')
    parser.add_argument('--skip-build', action='store_true', help='Reuse compiled local reactor and Surefire classpath')
    args = parser.parse_args()
    work = ROOT / 'target/python-migration-p0'
    work.mkdir(parents=True, exist_ok=True)
    log = work / 'baseline.log'
    log.write_text('')
    if not args.skip_build:
        run(['mvn', '-o', '-pl', 'Reactor-agent-app', '-am', 'test', '-DskipTests=false',
             '-Dtest=SseEmitterAgentSessionStreamTest', '-Dsurefire.failIfNoSpecifiedTests=false'], log)
    cp, agent = classpath()
    classes = work / 'classes'
    classes.mkdir(exist_ok=True)
    sources = list((ROOT / 'tests/python_migration/java').glob('*.java'))
    run(['javac', '-encoding', 'UTF-8', '-cp', cp, '-d', str(classes), *map(str, sources)], log)
    # Private test workspace: file tests and in-memory H2 cannot touch real stores.
    with tempfile.TemporaryDirectory(prefix='reactor-p0-') as temporary:
        out = work / 'captured'
        out.mkdir(exist_ok=True)
        run(['java', f'-javaagent:{agent}', f'-Djava.io.tmpdir={temporary}', '-Duser.timezone=Asia/Shanghai',
             '-cp', str(classes) + os.pathsep + cp, 'CaptureBaseline', str(ROOT), str(out), *TESTS], log)
    run(['java', '-cp', str(classes) + os.pathsep + cp, 'InspectH2Config', str(ROOT), str(work / 'config-presence.json')], log)
    from compare import compare, protocol_view
    for name in ('java-behavior.json', 'runtime-routes.json', 'tool-schemas.json'):
        current = json.loads((out / name).read_text())
        golden = ASSETS / name
        if args.record:
            golden.write_text(json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
        else:
            expected=json.loads(golden.read_text())
            differences = compare(protocol_view(expected), protocol_view(current)) if name == 'java-behavior.json' else compare(expected,current)
            if differences:
                raise SystemExit(name + ':\n' + '\n'.join(differences[:30]))
        print(f'{name}: {"recorded" if args.record else "PASS"}')
    result = json.loads((out / 'test-results.json').read_text())
    print(f'JUnit: {result["tests"]} tests, {result["failures"]} failures; deployment-only exclusions documented in test-results.json')
    print(f'Logs and raw captures: {work}')

if __name__ == '__main__':
    main()
