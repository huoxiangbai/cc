"""HTTP bridge to existing reactor-tool docread/dataprep runners."""
import asyncio
import json
from importlib.resources import files
from pathlib import Path
from reactor_backend.models.types import ToolReply, encode


class ToolAPI:
    def __init__(self, client, base_url, workspace_root, timeout=210, concurrency=128, *, settings=None, model=None):
        self.client, self.base_url = client, base_url.rstrip("/")
        self.workspace_root, self.timeout = Path(workspace_root), timeout
        self.gate = asyncio.Semaphore(concurrency)
        self.settings,self.model=settings,model
        self.headers={"X-Reactor-Service-Token":settings.tool_service_token} if settings and settings.tool_service_token else {}
        self.catalog = json.loads(files("reactor_backend.tools").joinpath("schemas.json").read_text())
        self.schemas = list(self.catalog.values())

    async def execute(self, name, arguments, query):
        if name not in self.catalog and name!='web_fetch':
            return ToolReply(failed=True, error=f"Unknown tool: {name}")
        root = (self.workspace_root / query.session_id).resolve()
        # Session ID is a directory segment, matching Java workspace resolver boundaries.
        if root.parent != self.workspace_root.resolve() or query.session_id in (".", ".."):
            return ToolReply(failed=True, error="Invalid session workspace")
        if getattr(self,'resources',None):
            await self.resources.namespace(query.visitor_id,query.session_id)
        body = {**{k:v for k,v in arguments.items() if not k.startswith('_')}, "requestId": query.session_id, "workspace_root": str(root)}
        if name == "code_execution":body["workspaceRoot"]=str(root)
        if name == "bash":
            body["workspaceRoot"]=str(root)
            body["timeoutSeconds"]=min(600,max(1,int(arguments.get("timeout_sec",120))))
            body["skillLibraryRoot"]=arguments.get('_skill_library')
            body["disabledSkillNames"]=arguments.get('_disabled_skills',[])
        try:
            async with self.gate, asyncio.timeout(self.timeout):
                response = await self.client.post(self.base_url + "/v1/tool/" + name, json=body, headers=self.resources.scope_headers(query.visitor_id,query.session_id) if getattr(self,'resources',None) else self.headers)
                if response.status_code >= 500:
                    return ToolReply(failed=True, error=f"{name} 执行失败：HTTP {response.status_code}")
                payload = response.json()
                if name=='bash':
                    if response.status_code>=400 or payload.get('message') and payload.get('exitCode',payload.get('exit_code')) is None:
                        return ToolReply(failed=True,error=payload.get('message') or 'bash service rejected request',structured_output=payload)
                    produced=payload.get('fileInfo') or payload.get('file_info') or []
                    result={'tool':'bash','ok':True,'exit_code':payload.get('exitCode',payload.get('exit_code')),
                        'stdout':payload.get('stdout') or '', 'stderr':payload.get('stderr') or '', 'truncated':bool(payload.get('truncated')),
                        'timed_out':bool(payload.get('timedOut',payload.get('timed_out'))),'duration_ms':payload.get('durationMs',payload.get('duration_ms',0)), 'cwd':'.'}
                    if produced:result['produced_files']=[{'file_name':f['fileName'],'url':f.get('domainUrl') or f.get('ossUrl'),'file_size':f.get('fileSize')} for f in produced]
                    return ToolReply(data=result,files=produced,structured_output=payload)
                if name=='code_execution':
                    produced=payload.get('fileInfo') or []
                    result={'tool':name,**{k:v for k,v in payload.items() if k not in ('fileInfo','workspaceRoot')}}
                    result['ok']=response.status_code<400 and payload.get('status')=='ok'
                    if produced:
                        result['produced_files']=[{'file_name':f['fileName'],'url':f.get('domainUrl') or f.get('ossUrl'),'file_size':f.get('fileSize')} for f in produced]
                    return ToolReply(data=result,files=produced,structured_output=payload,failed=not result['ok'],
                                     error=payload.get('error') if not result['ok'] else None,timed_out=payload.get('status')=='timeout')
                if response.status_code >= 400 or payload.get("success") is False or payload.get("status") in ("error","timeout") or payload.get("code") not in (None,200,"200","0000"):
                    return ToolReply(failed=True, error=f'{name} 执行失败：{payload.get("message") or payload.get("error") or "remote request rejected"}',files=payload.get("fileInfo") or [],structured_output=payload,timed_out=payload.get("status")=="timeout")
                data = payload.get("data")
                if data is not None:
                    encoded = data if isinstance(data, str) else encode(data)
                    if len(encoded) > 12000:
                        data = encoded[:12000] + "...[truncated]"
                produced = payload.get("fileInfo") or []
                result = {"tool": name, "ok": True}
                if data is not None:
                    result["data"] = data
                if payload.get("message"):
                    result["message"] = payload["message"]
                for key in ('stats','warnings','lint_warnings','templates','template','themes','theme','payload','resolved','colors','usage','saved','deleted','name','kind','path','variables','chart_type','format','rendered'):
                    if payload.get(key) is not None:
                        limit=2000 if key=='rendered' else 3000
                        result[key]=payload[key] if not isinstance(payload[key],str) else payload[key][:limit]+('...[truncated]' if len(payload[key])>limit else '')
                if name in ('document_generate','slides_generate','excel_generator','checklist_generate','chart_generator') and not produced:
                    return ToolReply(failed=True,error=name+' 生成了本地内容，但文件服务未登记交付物',structured_output=payload)
                if produced:
                    result["produced_files"] = [{"file_name": f["fileName"], "file_size": f.get("fileSize")} for f in produced]
                return ToolReply(data=result, files=produced, structured_output=payload)
        except (TimeoutError, asyncio.TimeoutError):
            return ToolReply(failed=True, error=f"{name} 执行超时", timed_out=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            import httpx
            return ToolReply(failed=True, error=f"{name} 执行失败：{type(exc).__name__}", timed_out=isinstance(exc, httpx.TimeoutException))

    def timeout_for(self,name):
        return getattr(self.settings,'research_timeout',600) if name in ('deep_search','multimodalagent_tool','code_interpreter','data_analysis') else self.timeout

    async def execute_scoped(self,name,arguments,query,emit):
        root=(self.workspace_root / query.session_id).resolve()
        if root.parent!=self.workspace_root.resolve() or query.session_id in ('.','..'):
            return ToolReply(failed=True,error='Invalid session workspace')
        if getattr(self,'resources',None):
            await self.resources.namespace(query.visitor_id,query.session_id)
            if name=='multimodalagent_tool':
                for kb in getattr(self.settings,'mrag_kb_ids',()):await self.resources.require(query.visitor_id,'kb',kb)
                if not getattr(self.settings,'mrag_kb_ids',()):return ToolReply(failed=True,error='必须明确配置有权限的知识库')
        from reactor_backend.adapters.research_tools import ResearchTools,REMOTE,SOCIAL
        from reactor_backend.adapters.web_search import WebSearch
        from reactor_backend.adapters.web_fetch import WebFetch
        if name in REMOTE or name in SOCIAL:return await ResearchTools(self,self.model,self.settings).execute(name,arguments,query,emit)
        if name=='WebSearch':return await WebSearch(self.client,getattr(self.settings,'web_search',{})).execute(arguments)
        if name=='WebFetch':return await WebFetch(self,self.model).execute(arguments,query)
        return await self.execute(name,arguments,query)
