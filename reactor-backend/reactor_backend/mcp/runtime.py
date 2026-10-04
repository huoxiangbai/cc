import asyncio
from contextlib import AsyncExitStack
from datetime import timedelta
import json
import re
from urllib.parse import urlparse
import httpx
from reactor_backend.models.types import ToolReply,encode


def segment(value):
    return re.sub(r'[^A-Za-z0-9_-]','_',str(value or '').strip())[:64] or 'unknown'


def descriptor(row):
    cfg=row.get('transport_config') or {};cfg=json.loads(cfg) if isinstance(cfg,str) else dict(cfg)
    kind=row['transport_type'];key=segment(row.get('mcp_name') or row['mcp_id'])
    if kind=='stdio':
        entries=cfg.get('stdio',{})
        cfg=entries.get(row.get('mcp_name')) or next(iter(entries.values())) if entries else cfg
        if not cfg.get('command'):raise ValueError('STDIO command required')
    elif kind in ('sse','streamable_http'):
        endpoint=cfg.get('sseEndpoint','') if kind=='sse' else cfg.get('endpoint','/mcp')
        cfg['url']=cfg.get('url') or str(cfg.get('baseUri','')).rstrip('/')+'/'+str(endpoint).lstrip('/')
        if urlparse(cfg['url']).scheme not in ('http','https'):raise ValueError('MCP HTTP URL required')
    else:raise ValueError('Unknown MCP transport: '+kind)
    return {**cfg,'kind':kind,'id':row['mcp_id'],'key':key,'timeout':max(1,row.get('request_timeout') or 180)*(1 if kind=='stdio' else 60)}


class Connection:
    """SDK context managers stay in one owner task; queue serializes STDIO requests."""
    def __init__(self,config):
        self.config=config;self.queue=asyncio.Queue();self.task=None;self.ready=None

    async def start(self):
        self.ready=asyncio.get_running_loop().create_future();self.task=asyncio.create_task(self._run())
        try:await asyncio.wait_for(asyncio.shield(self.ready),min(self.config['timeout'],30))
        except BaseException:
            await self.close();raise
        return self

    async def _run(self):
        from mcp import ClientSession,StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.sse import sse_client
        from mcp.client.streamable_http import streamablehttp_client
        cfg=self.config;pending=None
        try:
            async with AsyncExitStack() as stack:
                if cfg['kind']=='stdio':
                    streams=await stack.enter_async_context(stdio_client(StdioServerParameters(command=cfg['command'],args=cfg.get('args',[]),env=cfg.get('env') or {})))
                else:
                    def client_factory(headers=None,timeout=None,auth=None):
                        return httpx.AsyncClient(headers=headers,timeout=timeout,auth=auth,trust_env=False)
                    transport=sse_client(cfg['url'],headers=cfg.get('headers'),timeout=cfg['timeout'],sse_read_timeout=cfg['timeout'],httpx_client_factory=client_factory) if cfg['kind']=='sse' else streamablehttp_client(cfg['url'],headers=cfg.get('headers'),timeout=timedelta(seconds=cfg['timeout']),sse_read_timeout=timedelta(seconds=cfg['timeout']),httpx_client_factory=client_factory)
                    streams=await stack.enter_async_context(transport)
                session=await stack.enter_async_context(ClientSession(streams[0],streams[1],read_timeout_seconds=timedelta(seconds=cfg['timeout'])))
                await session.initialize();self.ready.set_result(True)
                while True:
                    item=await self.queue.get()
                    if item is None:break
                    method,args,pending=item
                    try:
                        result=await getattr(session,method)(**args)
                        if not pending.done():pending.set_result(result.model_dump(mode='json',by_alias=True,exclude_none=True))
                    except Exception as exc:
                        if not pending.done():pending.set_exception(exc)
                    finally:pending=None
        except BaseException as exc:
            if self.ready and not self.ready.done():self.ready.set_exception(RuntimeError('MCP initialization failed: '+str(exc)))
            if pending and not pending.done():pending.set_exception(RuntimeError('MCP connection closed'))
        finally:
            while not self.queue.empty():
                item=self.queue.get_nowait()
                if item and not item[2].done():item[2].set_exception(RuntimeError('MCP connection closed'))

    async def request(self,method,**args):
        if not self.task or self.task.done():raise RuntimeError('MCP connection is closed')
        future=asyncio.get_running_loop().create_future();await self.queue.put((method,args,future))
        return await asyncio.wait_for(future,self.config['timeout'])

    async def close(self):
        if self.task:
            await self.queue.put(None)
            try:await asyncio.wait_for(asyncio.shield(self.task),5)
            except TimeoutError:
                self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)


class Catalog:
    def __init__(self,rows,disabled=(),allowed=None,denied=()):
        self.rows=rows;self.disabled=set(disabled);self.allowed=allowed;self.denied=set(denied)
        self.connections={};self.tools={};self.active=set();self.resources=[];self.errors={}

    async def initialize(self):
        try:
            for row in self.rows:
                cfg=descriptor(row)
                if cfg['id'] in self.disabled or cfg['key'] in self.disabled:continue
                try:
                    connection=await Connection(cfg).start();self.connections[cfg['id']]=connection
                    cursor=None
                    while True:
                        result=await connection.request('list_tools',**({'cursor':cursor} if cursor else {}))
                        for tool in result.get('tools',[]):
                            name='mcp__'+cfg['key']+'__'+segment(tool['name'])
                            if name in self.denied or self.allowed is not None and '*' not in self.allowed and name not in self.allowed:continue
                            if name in self.tools:raise ValueError('MCP FQ name collision: '+name)
                            self.tools[name]=dict(name=name,original_name=tool['name'],server=cfg['key'],mcpId=cfg['id'],description=(tool.get('description') or tool.get('title') or tool['name']+' (MCP)')+(' ['+cfg['key']+' MCP]' if tool.get('description') or tool.get('title') else ''),searchHint=(tool.get('_meta') or {}).get('anthropic/searchHint',''),parameters=tool.get('inputSchema') or {'type':'object','properties':{},'required':[]})
                            if str((tool.get('_meta') or {}).get('anthropic/alwaysLoad','')).lower() in ('true','1','yes'):self.active.add(name)
                        cursor=result.get('nextCursor')
                        if not cursor:break
                    await self.refresh_resources(cfg['id'])
                except Exception as exc:
                    self.errors[cfg['id']]=type(exc).__name__+': '+str(exc)
                    conn=self.connections.pop(cfg['id'],None)
                    if conn:await conn.close()
                    self.tools={k:v for k,v in self.tools.items() if v['mcpId']!=cfg['id']}
                    self.active.intersection_update(self.tools)
        except BaseException:
            await self.close();raise

    def schemas(self):
        return [{'type':'function','function':{k:v for k,v in self.tools[n].items() if k in ('name','description','parameters')}} for n in self.tools if n in self.active]

    def prompt(self):
        names=sorted(set(self.tools)-self.active,key=str.lower)
        body='<available-deferred-tools>\n'+'\n'.join(names)+'\n</available-deferred-tools>\nUse ToolSearch before invoking deferred tools.' if names else ''
        if self.errors:body+='\nMCP servers unavailable: '+encode(self.errors)
        return body

    def server_id(self,server):
        for id,c in self.connections.items():
            if segment(server).lower() in (segment(id).lower(),c.config['key'].lower()):return id
        raise ValueError('Unknown, disabled or unavailable MCP server')

    async def refresh_resources(self,id):
        connection=self.connections[id];cursor=None;found=[]
        while True:
            try:result=await connection.request('list_resources',**({'cursor':cursor} if cursor else {}))
            except Exception as exc:
                if '-32601' in str(exc) or 'Method not found' in str(exc):return
                raise
            found.extend({**{k:r.get(k) for k in ('uri','name','title','description','mimeType','size')},'server':connection.config['key'],'mcpId':id} for r in result.get('resources',[]))
            cursor=result.get('nextCursor')
            if not cursor:break
        self.resources=[r for r in self.resources if r['mcpId']!=id]+found

    async def execute(self,name,args):
        try:
            if name=='ToolSearch':
                if not self.tools:return ToolReply(data=dict(tool=name,ok=True,matches=[],query='',total_deferred_tools=0,message='No deferred MCP tools in catalog'))
                query=str(args.get('query') or '').strip()
                try:maximum=int(args.get('max_results',5))
                except (ValueError,TypeError):maximum=5
                maximum=5 if maximum<=0 else min(maximum,50)
                found=self.search(query,maximum)
                activated={v['name'] for v in found}-self.active;self.active.update(v['name'] for v in found)
                matches=[{**{k:v[k] for k in ('name','original_name','server','description')},'parameters':encode(v['parameters']),'activated':True} for v in found]
                return ToolReply(data=dict(tool=name,ok=True,matches=matches,query=query,activated_count=len(activated),total_catalog_tools=len(self.tools),remaining_deferred_tools=len(set(self.tools)-self.active),message='Activated '+str(len(activated))+' tool(s); call them by name on the next turn' if found else 'No matching deferred tools'))
            if name=='ListMcpResources':
                id=self.server_id(args['server']) if args.get('server') else None
                for key in ([id] if id else self.connections):await self.refresh_resources(key)
                selected=[r for r in self.resources if not id or r['mcpId']==id]
                return ToolReply(data=dict(tool=name,ok=True,resources=selected,count=len(selected)))
            if name=='ReadMcpResource':
                id=self.server_id(args.get('server'));result=await self.connections[id].request('read_resource',uri=args['uri'])
                contents=[]
                for item in result.get('contents',[]):
                    if 'text' in item:contents.append(item['text'])
                    elif 'blob' in item:contents.append('[blob resource uri='+str(item.get('uri') or args['uri'])+', mimeType='+str(item.get('mimeType') or '')+', base64Length='+str(len(item['blob']))+', mcpId='+id+']')
                    else:contents.append(encode(item))
                return ToolReply(data=dict(tool=name,ok=True,server=args['server'],uri=args['uri'],content='\n'.join(contents) if contents else 'Resource empty: '+args['uri']))
            if name not in self.active:raise PermissionError('ToolSearch must activate MCP tool before invocation')
            tool=self.tools[name];result=await self.connections[tool['mcpId']].request('call_tool',name=tool['original_name'],arguments=args)
            text='\n'.join(c['text'] for c in result.get('content',[]) if c.get('type')=='text' and c.get('text','').strip())
            detail=text or encode(result.get('structuredContent') or result.get('content') or result)
            failed=result.get('isError',False)
            return ToolReply(data=detail,structured_output=result,failed=failed,error=detail if failed else None,wire_observation='Tool'+tool['original_name']+' Error. '+detail if failed else None)
        except Exception as exc:return ToolReply(failed=True,error=name+' failed: '+str(exc))

    def search(self,query,maximum):
        if query.lower().startswith('select:'):
            found=[]
            for name in re.split(r'[,\s]+',query[7:]):
                match=next((v for v in self.tools.values() if name.lower() in (v['name'].lower(),v['original_name'].lower())),None)
                if match and match not in found:found.append(match)
                if len(found)>=maximum:break
            return found
        deferred=[v for k,v in self.tools.items() if k not in self.active]
        if not query:return deferred[:maximum]
        required=[t[1:].lower() for t in query.split() if t.startswith('+') and len(t)>1]
        terms=[t.lower() for t in query.split() if not (t.startswith('+') and len(t)>1)]
        scored=[]
        for v in deferred:
            hay=' '.join(str(v[k]) for k in ('name','original_name','server','description','searchHint','parameters')).lower()
            if not all(t in hay for t in required):continue
            lower=v['name'].lower()
            score=sum(100 if t==lower else 40 if t in lower else 10 if t in hay else 0 for t in terms) if terms else 1
            if score:scored.append((score,v))
        return [v for _,v in sorted(scored,key=lambda item:-item[0])[:maximum]]

    async def close(self):
        await asyncio.gather(*(c.close() for c in self.connections.values()))
        self.connections.clear()
