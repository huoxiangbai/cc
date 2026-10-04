"""Real GenUI/canvas tools; typed facts are replayed by the existing projector."""
import asyncio
import json
import os
import mimetypes
from importlib.resources import files
from pathlib import Path
from reactor_backend.models.types import ToolReply,encode
from reactor_backend.projection.genui import tree,patch

PAYLOADS=json.loads(files('reactor_backend').joinpath('resources/genui_payloads.json').read_text())
NAMES={'emit_ui_tree','emit_ui_patch','canvas_publish','get_genui_guide','get_html_canvas_guide','list_ui_components'}

async def register(scope,path):
    workspace=scope.workspace;api=scope.runtime.tools
    parts=workspace.parts(path);relative='/'.join(parts)
    def verify():
        with workspace.opened(relative,os.O_RDONLY) as fd:return os.fstat(fd).st_size
    size=await asyncio.to_thread(verify)
    if getattr(api,'resources',None):await api.resources.require(scope.query.visitor_id,'file_scope',scope.query.session_id)
    response=await api.client.post(api.base_url+'/v1/file_tool/register_file',json={'requestId':scope.query.session_id,'fileName':relative,'localPath':str(workspace.root/workspace.session/relative),'description':'workspace:'+relative},headers=api.headers)
    response.raise_for_status();value=response.json()
    return {**value,'relativePath':relative,'originFileName':relative,'previewUrl':value['domainUrl'],'mimeType':mimetypes.guess_type(relative)[0],'fileSize':size}

async def execute(scope,name,a):
    if name in ('get_genui_guide','get_html_canvas_guide'):return ToolReply(data=PAYLOADS[name])
    if name=='list_ui_components':return ToolReply(data={'tool':name,'ok':True,'node_shape':'{"kind":"...","props":{...},"children":[...]}','rules':['Every component prop goes inside props.','children is only for nested nodes, never strings.','Omit nodeId unless you need stable emit_ui_patch targets.'],'components':PAYLOADS['components']})
    if name=='emit_ui_tree':
        raw=a.get('tree')
        if isinstance(raw,str):raw=json.loads(raw)
        normalized=tree(raw);canvas=str(a.get('canvas_id') or '').strip() or None
        return ToolReply(data={'tool':name,'ok':True,'message':'GenUI tree emitted successfully. Prefer emit_ui_patch for small updates.','canvasId':canvas,'salvaged':False,'tree':normalized},structured_output={'canvas_id':canvas,'salvaged':False,'tree_json':encode(normalized)})
    if name=='emit_ui_patch':
        normalized=patch(a);seq=normalized.get('seq');seq=int(seq) if isinstance(seq,(int,float)) and not isinstance(seq,bool) else None
        return ToolReply(data={'tool':name,'ok':True,'message':f"GenUI patch applied ({len(normalized['patches'])} ops).",'canvasId':normalized.get('canvas_id'),'seq':seq,'patchCount':len(normalized['patches'])},structured_output={'canvas_id':normalized.get('canvas_id'),'seq':seq,'patches_json':encode(normalized['patches'])})
    path=str(a.get('html_path') or '').strip()
    if Path(path).is_absolute():
        try:path=str(Path(path).relative_to(scope.workspace.root/scope.workspace.session))
        except ValueError:raise ValueError('html_path must be inside the session workspace') from None
    if not path:raise ValueError('html_path is required')
    info=await register(scope,path);title=str(a.get('title') or 'Canvas');opened=a.get('open_in_panel',True) is not False
    return ToolReply(data={'tool':name,'ok':True,'message':'Canvas published.','title':title,'mode':'html','fileName':info['fileName'],'relativePath':info['relativePath'],'openInPanel':opened,'salvaged':False},files=[info],structured_output={'title':title,'mode':'html','primary_file_name':info['fileName'],'preview_url':info['previewUrl'],'download_url':info['downloadUrl'],'open_in_panel':opened,'salvaged':False})
