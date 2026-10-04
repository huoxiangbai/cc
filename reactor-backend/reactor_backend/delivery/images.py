"""One production kernel shared by HTTP and Agent, with original typed batch storage."""
import asyncio
from sqlalchemy import text
from reactor_backend.adapters.mysql import rows
from reactor_backend.models.types import ToolReply,ToolCall,encode
from reactor_backend.delivery.artifacts import artifact_values
from reactor_backend.adapters.image_gateway import ImageGateway
from reactor_backend.projection.history import iso

class Images:
    def __init__(self,ledger,client,api,config):self.ledger,self.api=ledger,api;self.gateway=ImageGateway(client,api,config);self.gate=asyncio.Semaphore(8);self.workspace_lock=asyncio.Lock()
    @staticmethod
    def structured(result):
        return {key:result.get(wire) for key,wire in [('prompt','prompt'),('mode','mode'),('summary','data'),('size','size'),('batch_count','batchCount'),('source_image_count','sourceImageCount'),('mask_image_count','maskImageCount'),('used_fallback','usedFallback')]}
    async def tool(self,scope,args):
        a=dict(args);attached=scope.query.session_files or []
        def reference(file):return file.get('previewUrl') or file.get('domainUrl') or file.get('downloadUrl') or file.get('ossUrl') or file.get('fileName') or file.get('name')
        def normalize(value):return [str(x).strip() for x in value if x and str(x).strip()] if isinstance(value,list) else [x.strip() for x in __import__('re').split('[,，]',str(value or '')) if x.strip()]
        source=normalize(a.get('fileNames'))
        if not source and a.get('mode') in (None,'','edits'):
            source=[reference(f) for f in attached if str(f.get('fileName') or f.get('name') or '').lower().endswith(('.png','.jpg','.jpeg','.gif','.webp','.bmp','.svg'))]
        def mapped(value):
            return next((reference(f) for f in attached if str(f.get('fileName') or f.get('name') or '').rsplit('/',1)[-1].lower()==value.rsplit('/',1)[-1].lower()),value) if not value.startswith(('http:','https:','data:')) else value
        a.update(fileNames=[mapped(x) for x in source],maskFileNames=[mapped(x) for x in normalize(a.get('maskFileNames'))])
        try:
            result=await self.gateway.generate(a,scope.query)
            data=dict(tool='image_generation',ok=True,summary=result['data'],prompt=result['prompt'],mode=result['mode'],size=result['size'],batchCount=result['batchCount'],produced_files=[dict(file_name=f['fileName'],mimeType=f['mimeType'],url=f['previewUrl']) for f in result['fileInfo']],hint='Use produced_files.url as image.url for document_generate when needed.')
            return ToolReply(data=data,files=result['fileInfo'],structured_output=self.structured(result))
        except Exception as exc:
            message='image_generation_tool 执行失败：'+str(exc)
            return ToolReply(failed=True,error=message,structured_output={'summary':message},wire_observation=message)
    async def workspace(self,args,query):
        # Single-worker gate keeps duplicate request IDs from materializing files twice.
        async with self.gate:
            async with self.workspace_lock:
                existing=await self.ledger.transact(lambda c:rows(c,'SELECT id FROM ai_agent_tool_output_image_generation WHERE request_id=:req',req=query.session_id))
                if existing:raise ValueError('requestId 对应批次已存在')
                return await self._workspace(args,query)
    async def _workspace(self,args,query):
        result=await self.gateway.generate(args,query);call=ToolCall('workspace-image-generation-'+query.session_id,'image_generation_tool','{}')
        values=self.structured(result);values.update(request_id=query.session_id,request_source='workspace',session_id=query.session_id,tool_call_id=call.id,status=1)
        def save(c):
            if rows(c,'SELECT id FROM ai_agent_tool_output_image_generation WHERE request_id=:req AND tool_call_id=:call FOR UPDATE',req=query.session_id,call=call.id):raise ValueError('requestId 对应批次已存在')
            cols=','.join(values);params=','.join(':'+k for k in values)
            c.execute(text(f'INSERT INTO ai_agent_tool_output_image_generation ({cols}) VALUES ({params})'),values)
            for file in result['fileInfo']:
                value=artifact_values({'id':None,'request_id':query.session_id},None,call,file);cols=','.join(value);params=','.join(':'+k for k in value)
                c.execute(text(f'INSERT INTO ai_agent_artifact ({cols}) VALUES ({params})'),value)
        await self.ledger.transact(save)
        return {k:result[k] for k in ('data','fileInfo','requestId','mode','usedFallback','rawResponse')}
    async def history(self,visitor,page,size):
        def read(c):
            where="request_source='workspace' AND EXISTS(SELECT 1 FROM reactor_private_resource_owner p WHERE p.resource_kind='image_batch' AND p.resource_key=i.request_id AND p.visitor_id=:visitor)"
            total=rows(c,f'SELECT COUNT(*) n FROM ai_agent_tool_output_image_generation i WHERE {where}',visitor=visitor)[0]['n']
            batches=rows(c,f'SELECT i.* FROM ai_agent_tool_output_image_generation i WHERE {where} ORDER BY created_at DESC,id DESC LIMIT :offset,:size',visitor=visitor,offset=(max(1,page)-1)*min(50,size if size>0 else 10),size=min(50,size if size>0 else 10))
            output=[]
            for row in batches:
                artifacts=rows(c,'SELECT * FROM ai_agent_artifact WHERE request_id=:req AND tool_call_id=:call AND deleted=0 ORDER BY id',req=row['request_id'],call=row['tool_call_id'])
                images=[dict(fileName=f['file_name'],ossUrl=f['download_url'],domainUrl=f['preview_url'],downloadUrl=f['download_url'],previewUrl=f['preview_url'],fileSize=f['file_size'],mimeType=f['mime_type']) for f in artifacts]
                output.append(dict(requestId=row['request_id'],prompt=row['prompt'],mode=row['mode'],size=row['size'],batchCount=row['batch_count'],sourceImageCount=row['source_image_count'],maskImageCount=row['mask_image_count'],usedFallback=bool(row['used_fallback']),createdAt=iso(row['created_at']),images=images))
            return dict(total=total,list=output)
        return await self.ledger.transact(read)
