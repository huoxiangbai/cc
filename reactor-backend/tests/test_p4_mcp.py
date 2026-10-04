import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import httpx
import pytest
from reactor_backend.mcp.runtime import Catalog,descriptor,segment


@pytest.mark.parametrize('kind',['sse','stdio','streamable_http'])
async def test_real_mcp_transport_discovery_wire_resources_isolation_shutdown(tmp_path,kind):
    server=Path(__file__).with_name('p4_mcp_endpoint.py');process=None
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    cfg={'command':sys.executable,'args':[str(server),'--transport','stdio']} if kind=='stdio' else {'baseUri':f'http://127.0.0.1:{port}','sseEndpoint':'/sse','endpoint':'/mcp'}
    row=dict(mcp_id='id-'+kind,mcp_name='Server ! '+kind,transport_type=kind,transport_config=json.dumps(cfg),request_timeout=1)
    if kind!='stdio':
        log=(tmp_path/'server.log').open('w')
        process=subprocess.Popen([sys.executable,str(server),'--transport','streamable-http' if kind=='streamable_http' else 'sse','--port',str(port)],stdout=log,stderr=log,env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','TMPDIR')})
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(200):
                try:await client.get(f'http://127.0.0.1:{port}/',timeout=.2);break
                except httpx.HTTPError:await asyncio.sleep(.05)
            else:raise RuntimeError('MCP server did not start: '+(tmp_path/'server.log').read_text())
    catalog=Catalog([row]);other=Catalog([row]);disabled=Catalog([row],[row['mcp_id']])
    try:
        await catalog.initialize();assert not catalog.errors,catalog.errors
        await other.initialize();await disabled.initialize();assert disabled.tools=={}
        echo='mcp__'+segment(row['mcp_name'])+'__original_echo_'
        assert echo in catalog.tools and echo not in catalog.active
        assert (await catalog.execute(echo,{'text':'premature'})).failed
        searched=await catalog.execute('ToolSearch',{'query':'select:'+echo})
        assert searched.data['activated_count']==1 and echo not in other.active
        result=await catalog.execute(echo,{'text':'实际中文参数'})
        assert not result.failed and '实际中文参数' in str(result.data) and 'original.echo!' in str(result.data)
        resources=await catalog.execute('ListMcpResources',{})
        assert resources.data['count']==1
        read=await catalog.execute('ReadMcpResource',{'server':row['mcp_id'],'uri':'p4://manual'})
        assert not read.failed and '真实 MCP resource' in str(read.data)
        assert any(s['function']['name'].endswith('__always') for s in catalog.schemas())
        tasks=[c.task for c in catalog.connections.values()]
        await catalog.close();assert all(t.done() for t in tasks)
    finally:
        await catalog.close();await other.close();await disabled.close()
        if process:process.terminate();process.wait(timeout=10);log.close()


def test_descriptor_supports_original_nested_stdio_and_timeout_units():
    row=dict(mcp_id='id',mcp_name='orig',transport_type='stdio',transport_config={'stdio':{'orig':{'command':'python','args':['a.py'],'env':{'TEST':'value'}}}},request_timeout=2)
    cfg=descriptor(row);assert cfg['command']=='python' and cfg['timeout']==2
