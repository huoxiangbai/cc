"""Authenticated public facade of original Tool paths. No arbitrary tool execution."""
import json
import asyncio
from urllib.parse import urlsplit,unquote
from fastapi import Request
from fastapi.responses import JSONResponse,Response,StreamingResponse
from reactor_backend.adapters.private_resources import ResourceDenied


def install_private_tool(app,resources,settings):
    api=resources.api
    @app.exception_handler(ResourceDenied)
    async def denied(request,exc):return JSONResponse({'detail':str(exc)},status_code=403)

    async def identify(request):
        scoped=request.headers.get('x-reactor-analysis-scope')
        if scoped:
            import hmac
            if not hmac.compare_digest(request.headers.get('x-reactor-service-token',''),settings.tool_service_token):
                raise ResourceDenied('无效内部认证')
            data=resources.verify_scope(scoped)
            await resources.require(data['visitor'],'file_scope',data['session'])
            return data['visitor'],data['session']
        return await resources.existing_identity(request.cookies.get(settings.cookie_name)),None
    app.state.private_identity=identify

    async def file_url(visitor,url):
        path=unquote(urlsplit(url).path)
        if '/v1/file_tool/' in path:
            pieces=path.split('/v1/file_tool/',1)[1].split('/')
            if pieces[0] not in ('preview','download') or len(pieces)<3:raise ResourceDenied('无效私有文件引用')
            await resources.require(visitor,'file_scope',pieces[1])
            return
        # Internal uploads to OSS are also scoped: do not let another visitor reuse
        # an uploaded private document's public-looking URL.
        from hashlib import sha256
        owner=await resources.owner('document_url',sha256(url.encode()).hexdigest())
        if owner and owner!=visitor:raise ResourceDenied('无权访问该文档引用')
    app.state.check_private_file_url=file_url

    async def gateway(path,request):
        target='/'+path
        public=request.method in ('GET','HEAD') and await app.state.featured.published(target)
        visitor,scope=(None,None) if public else await identify(request)
        content=await request.body()
        content_type=request.headers.get('content-type','')
        data={}
        if 'application/json' in content_type:
            try:data=json.loads(content)
            except ValueError:return Response(status_code=400)
            if not isinstance(data,dict):return Response(status_code=400)
        form=await request.form() if 'multipart/form-data' in content_type else {}
        action=target.rsplit('/',1)[-1]
        headers={**api.headers,'Content-Type':content_type}
        headers.update({key:request.headers[key] for key in ('range','if-range','if-none-match','if-modified-since') if key in request.headers})
        if scope:headers.update(resources.scope_headers(visitor,scope))
        created=None
        if target.startswith('/v1/file_tool/'):
            if action=='register_file':raise ResourceDenied('本地路径登记仅允许内部调用')
            parts=target.split('/')
            if len(parts)>=6 and parts[3] in ('preview','download'):
                key=parts[4]
                if not public:await resources.require(visitor,'file_scope',key)
            elif action in ('upload_file','upload_file_data'):
                key=data.get('requestId') or form.get('requestId')
                await resources.namespace(visitor,key)
            elif action=='get_file_list':
                await resources.require(visitor,'file_scope',data.get('requestId'))
                # Original filters query file IDs without respecting requestId.
                # Obtain each actual request scope before forwarding any filter.
                for item in data.get('filters') or []:
                    r=await api.client.post(api.base_url+'/v1/file_tool/get_file_list',json={'requestId':data['requestId'],'filters':[item]},headers=api.headers)
                    r.raise_for_status()
                    for f in r.json().get('results',[]):await resources.require(visitor,'file_scope',f['requestId'])
            elif action=='get_file':
                r=await api.client.post(api.base_url+'/v1/file_tool/get_file_list',json={'requestId':data.get('requestId')},headers=api.headers)
                r.raise_for_status()
                found=r.json().get('results',[])
                if not found:raise ResourceDenied('未知文件不能自动认领')
                await resources.require(visitor,'file_scope',data.get('requestId'))
                for f in found:await resources.require(visitor,'file_scope',f['requestId'])
            else:raise ResourceDenied('未授权文件操作')
        elif target.startswith('/v1/documents/'):
            allowed={'upload','create_knowledge_base','list_knowledge_base','delete_knowledge_base','add_files','add_web_url','delete_files','list_kb_files','get_file_full_content'}
            if action not in allowed:raise ResourceDenied('未授权知识库操作')
            if action=='create_knowledge_base':
                if data.get('kb_id'):
                    r=await api.client.post(api.base_url+'/_reactor/resource_exists',json={'kind':'kb','key':data['kb_id']},headers=api.headers)
                    r.raise_for_status()
                    if r.json()['exists']:raise ResourceDenied('已有知识库不能被创建接口覆盖')
                    await resources.claim_new(visitor,'kb',data['kb_id'])
                created=('kb','kb_id')
            elif action=='upload':created=('file_scope','document_id')
            elif action!='list_knowledge_base':
                await resources.require(visitor,'kb',data.get('kb_id'))
                if action=='add_web_url':await file_url(visitor,data.get('url',''))
                for file in data.get('files') or []:
                    await file_url(visitor,file.get('file_url',''))
                    path=unquote(urlsplit(file.get('file_url','')).path)
                    if '/v1/file_tool/' in path:
                        key=path.split('/v1/file_tool/',1)[1].split('/')[1]
                        headers.update(resources.scope_headers(visitor,key))
            if action=='list_knowledge_base':return await filtered_list(target,data,visitor,'kb','kb_id','list')
        elif target.startswith('/v1/mrag/sessions/'):
            if action=='create':
                for kb in data.get('kb_ids') or ([data['kb_id']] if data.get('kb_id') else []):await resources.require(visitor,'kb',kb)
                created=('mrag_session','session_id')
            elif action=='list':return await filtered_list(target,data,visitor,'mrag_session','session_id','list')
            elif action in ('detail','delete'):await resources.require(visitor,'mrag_session',data.get('session_id'))
            else:raise ResourceDenied('未授权历史操作')
        elif target=='/v1/tool/mragQuery':
            kbs=data.get('kb_ids') or ([data['kb_id']] if data.get('kb_id') else [])
            if data.get('session_id'):
                await resources.require(visitor,'mrag_session',data['session_id'])
                r=await api.client.post(api.base_url+'/v1/mrag/sessions/detail',json={'session_id':data['session_id']},headers=api.headers);r.raise_for_status()
                kbs=kbs or r.json()['data']['session']['kb_scope']
            if not kbs:raise ResourceDenied('必须明确选择有权限的知识库')
            for kb in kbs:await resources.require(visitor,'kb',kb)
            for url in data.get('image_urls') or []:await file_url(visitor,url)
        elif target.startswith('/v1/sop/'):
            # Original SOP is shared configuration, not a private knowledge store.
            pass
        else:raise ResourceDenied('Tool执行仅允许内部调用')
        upstream=await api.client.send(api.client.build_request(request.method,api.base_url+target,content=content,headers=headers,params=request.query_params),stream=True)
        if created and upstream.status_code<400:
            raw=await upstream.aread()
            try:payload=json.loads(raw);value=payload.get('data') or {}
            except ValueError:await upstream.aclose();raise ValueError('Invalid Tool resource response')
            kind,field=created
            if value.get(field):
                await resources.claim_new(visitor,kind,value[field])
                for fieldname in ('preview_url','permanent_url','presigned_url'):
                    if value.get(fieldname):
                        from hashlib import sha256
                        await resources.claim_new(visitor,'document_url',sha256(value[fieldname].encode()).hexdigest(),value.get('document_id'))
            await upstream.aclose()
            return Response(raw,status_code=upstream.status_code,headers=forward_headers(upstream))
        async def stream():
            try:
                async for chunk in upstream.aiter_raw():yield chunk
            finally:await upstream.aclose()
        return StreamingResponse(stream(),status_code=upstream.status_code,headers=forward_headers(upstream))

    async def filtered_list(target,data,visitor,kind,idfield,listfield):
        owned=await resources.visible(visitor,kind);items=[];page=1
        while True:
            response=await api.client.post(api.base_url+target,json={**data,'page_no':page,'page_size':100},headers=api.headers)
            response.raise_for_status();payload=response.json();batch=(payload.get('data') or {}).get(listfield,[])
            items.extend(x for x in batch if x[idfield] in owned)
            if len(batch)<100:break
            page+=1
        size=max(1,min(100,int(data.get('page_size',20))));number=max(1,int(data.get('page_no',1)))
        payload['data'][listfield]=items[(number-1)*size:number*size]
        for key in ('total','total_count'):
            if key in payload['data']:payload['data'][key]=len(items)
        return JSONResponse(payload)

    def forward_headers(response):
        return {k:v for k,v in response.headers.items() if k.lower() in {'content-type','content-disposition','content-encoding','cache-control','x-accel-buffering','content-range','accept-ranges','etag','last-modified'}}

    @app.api_route('/v1/{path:path}',methods=['GET','POST','PUT','DELETE','PATCH','HEAD'])
    async def direct(path:str,request:Request):return await gateway('v1/'+path,request)
    @app.api_route('/tool/{path:path}',methods=['GET','POST','PUT','DELETE','PATCH','HEAD'])
    async def proxied(path:str,request:Request):return await gateway(path,request)

    @app.post('/api/agent/file/upload')
    async def conversation_upload(request:Request):
        visitor,_=await identify(request);form=await request.form()
        session=form.get('sessionId');file=form.get('file')
        if not session or file is None:return Response(status_code=400)
        try:await resources.ledger.owner(visitor,session,None,True)
        except ValueError as exc:raise ResourceDenied(str(exc)) from None
        await resources.namespace(visitor,session)
        raw=await file.read()
        if not raw:return Response(status_code=400)
        from reactor_backend.runtime.workspace import Workspace
        import os
        name=file.filename.replace('\\','/').rsplit('/',1)[-1]
        workspace=Workspace(settings.workspace_root,session)
        def write_input():
            with workspace.opened('input/'+name,os.O_WRONLY|os.O_CREAT,True) as fd:
                os.ftruncate(fd,0)
                remaining=raw
                while remaining:
                    n=os.write(fd,remaining);remaining=remaining[n:]
                os.fsync(fd)
        await asyncio.to_thread(write_input)
        r=await api.client.post(api.base_url+'/v1/file_tool/upload_file_data',data={'requestId':session},files={'file':(file.filename,raw,file.content_type)},headers=api.headers)
        r.raise_for_status();value=r.json()
        return JSONResponse({'name':file.filename,'url':value['domainUrl'],'previewUrl':value['domainUrl'],'downloadUrl':value['downloadUrl'],
                             'type':file.filename.rsplit('.',1)[-1].lower() if '.' in file.filename else '', 'size':len(raw),'resourceKey':session+':'+file.filename+':'+__import__('hashlib').sha256(raw).hexdigest(),'mimeType':file.content_type,'originFileName':file.filename})

    @app.get('/api/agent/workspace/{session}/archive')
    async def archive(session:str,request:Request):
        visitor,_=await identify(request)
        await resources.require(visitor,'file_scope',session)
        try:await resources.ledger.owner(visitor,session)
        except ValueError as exc:raise ResourceDenied(str(exc)) from None
        from reactor_backend.runtime.workspace import Workspace
        import io,zipfile,os
        import stat
        workspace=Workspace(settings.workspace_root,session)
        def build():
            buf=io.BytesIO();count=0;size=0
            with workspace.directory([]) as root,zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
                def visit(directory,prefix):
                    nonlocal count,size
                    for name in sorted(os.listdir(directory)):
                        info=os.stat(name,dir_fd=directory,follow_symlinks=False)
                        relative=prefix+name
                        if stat.S_ISLNK(info.st_mode):continue
                        if stat.S_ISDIR(info.st_mode):
                            child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
                            try:visit(child,relative+'/')
                            finally:os.close(child)
                        elif stat.S_ISREG(info.st_mode):
                            count+=1;size+=info.st_size
                            if count>10000 or size>512*1024*1024:raise ValueError('Workspace archive exceeds size/file budget; no partial archive returned')
                            with workspace.opened(relative,os.O_RDONLY) as fd,z.open(relative,'w') as output:
                                while chunk:=os.read(fd,65536):output.write(chunk)
                visit(root,'')
            return buf.getvalue()
        return Response(await asyncio.to_thread(build),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="workspace.zip"'})
