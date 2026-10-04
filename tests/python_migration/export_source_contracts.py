#!/usr/bin/env python3
"""Generate source-derived contracts; no configuration values or user data."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/python-migration/fixtures/source-contracts.json'


def build():
    contract=(ROOT/'docs/python-migration/contracts.md').read_text()
    routes=[]
    for line in contract.splitlines():
        match=re.match(r'\| (GET|POST|PUT|DELETE|PATCH|ANY|任意（未限定）) `([^`]+)` \| (.*?) \| (.*?) \| (.*?) \|',line)
        if match: routes.append(dict(zip(('verb','path','parameters','returns','source'),match.groups())))
    assert len(routes)==108, f'Route index drift: {len(routes)}'
    dtos=[]
    for module in ROOT.glob('Reactor-agent-*'):
        for p in sorted((module/'src/main/java').rglob('*.java')):
            if p.stem.endswith(('DTO','VO','Req','Response','GptProcessResult','AgentRequest')):
                source=p.read_text()
                fields=re.findall(r'^\s*private\s+(?!static|final)([\w<>?, .\[\]]+)\s+(\w+)\s*(?:=\s*([^;]+))?;',source,re.M)
                if fields:dtos.append({'source':str(p.relative_to(ROOT)),'class':p.stem,'fields':[{'javaType':t.strip(),'name':n,'initializer':v or None} for t,n,v in fields]})
    sqlite_models=[]
    candidates=[ROOT/'reactor-tool/reactor_tool/db/file_table.py']+list((ROOT/'reactor-tool/reactor_tool/tool/mrag/storage').rglob('*sqlite*.py'))
    for path in sorted(candidates):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node,ast.ClassDef):continue
            fields=[{'name':n.target.id,'pythonType':ast.unparse(n.annotation)} for n in node.body if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name)]
            table=[ast.unparse(n.value) for n in node.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__tablename__' for t in n.targets)]
            if table or fields:sqlite_models.append({'source':str(path.relative_to(ROOT)),'class':node.name,'table':table,'fields':fields,'evidence':'source-only, not a copied SQLite DDL'})
    mappers=[]
    for p in sorted((ROOT/'Reactor-agent-app/src/main/resources/mybatis/mapper').glob('*.xml')):
        element=ET.fromstring(p.read_text())
        statements=[{'kind':e.tag,'id':e.get('id'),'xml':ET.tostring(e,encoding='unicode')} for e in element if e.tag in ('insert','update','delete','select')]
        mappers.append({'source':str(p.relative_to(ROOT)),'namespace':element.get('namespace'),'statements':statements})
    py_routes=[]
    for p in sorted((ROOT/'reactor-tool/reactor_tool').rglob('*.py')):
        if '/api/' not in str(p):continue
        for node in ast.walk(ast.parse(p.read_text())):
            if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
            for d in node.decorator_list:
                if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and d.func.attr in ('get','post','put','delete','patch') and d.args and isinstance(d.args[0],ast.Constant):
                    py_routes.append({'source':str(p.relative_to(ROOT)),'line':node.lineno,'verb':d.func.attr.upper(),'routerPath':d.args[0].value,'handler':node.name,'arguments':ast.unparse(node.args),'evidence':'source-only; router prefix in api/__init__.py'})
    tool_returns=[]
    for path in sorted((ROOT/'Reactor-agent-domain/src/main/java').rglob('*.java')):
        source=path.read_text()
        if 'implements BaseTool' not in source:continue
        tool_returns.append({'source':str(path.relative_to(ROOT)),'evidence':'source-return-expressions; branches require behavior fixtures/live validation',
            'returns':[{'line':i,'expression':line.strip()} for i,line in enumerate(source.splitlines(),1) if re.search(r'\breturn\b',line)]})
    tools=[]
    for line in contract.splitlines():
        if line.startswith('| `') and '.java#L' in line and ('Tool.java' in line or 'ToolNames.java' in line): tools.append(line)
    schema=ROOT/'Reactor-agent-app/src/main/resources/db/schema.sql'
    tables=re.findall(r'CREATE TABLE\s+(?:IF NOT EXISTS\s+)?`?([\w]+)`?',schema.read_text(),re.I)
    return {'evidence':'source-derived, not invocation or live integration','javaRoutes':routes,'dtoFields':dtos,'pythonRouterMappings':py_routes,
            'sqliteModels':sqlite_models,'toolSourceIndex':tools,'toolReturnExpressions':tool_returns,'mysql':{'source':str(schema.relative_to(ROOT)),'sha256':hashlib.sha256(schema.read_bytes()).hexdigest(),'tables':tables},'mybatis':mappers,
            'fileAccess':{'source':'reactor-tool/reactor_tool/api/file_tool.py','rule':'Tool route/default/body index above; bytes, MIME, cookie/proxy/OSS and old file integration remain unverified'},
            'sseOrder':{'javaFrameType':'data-only JSON; no event/id/[DONE]','requiredEdges':[['tool_call','tool_result'],['root_result','stream_settle']],
                        'parallelToolCompletion':'partial order only','source':'contracts.md sections 2/3; runtime wire captured in java-behavior.json'},
            'upstreamFixtures':{'model':{'messages':[{'role':'assistant','content':None,'tool_calls':[{'id':'call-p0','type':'function','function':{'name':'WebFetch','arguments':'{"url":"https://example.test/page"}'}}]}, {'role':'assistant','content':'fixture final'}]},
                              'tool':{'tool':'WebFetch','ok':True,'url':'https://example.test/page','content':'isolated fixture content'},'evidence':'synthetic test input; not claimed as Java or provider capture'}}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--record',action='store_true');a=p.parse_args(); current=build()
    if a.record:OUT.write_text(json.dumps(current,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
    else:
        from compare import compare
        differences=compare(json.loads(OUT.read_text()),current)
        if differences:raise SystemExit('\n'.join(differences[:20]))
    print(f'Source contracts {"recorded" if a.record else "PASS"}: {len(current["javaRoutes"])} routes, {len(current["dtoFields"])} DTOs, {len(current["mybatis"])} mappers')
