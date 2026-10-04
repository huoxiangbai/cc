"""Complete HTTP/stream bridge to the unchanged reactor-tool implementation."""
import asyncio
import json
import httpx
from reactor_backend.adapters.tool_stream import events
from reactor_backend.models.types import ToolReply,encode
from reactor_backend.research.results import ResearchResult,report_name

REMOTE={'deep_search':'deepsearch','code_interpreter':'code_interpreter','data_analysis':'auto_analysis','multimodalagent_tool':'mragQuery'}
SOCIAL={'twitter','reddit','xueqiu'}


class ResearchTools:
    def __init__(self,api,model=None,settings=None):
        self.api,self.model,self.settings=api,model,settings

    async def upload(self,query,name,content,description):
        if getattr(self.api,'resources',None):await self.api.resources.namespace(query.visitor_id,query.session_id)
        response=await self.api.client.post(self.api.base_url+'/v1/file_tool/upload_file',json={
            'requestId':query.session_id,'fileName':name,'content':content,'description':description},headers=self.api.headers)
        response.raise_for_status()
        data=response.json()
        if data.get('code') not in (None,200,'200','0000'):raise ValueError('File upload rejected')
        return {'fileName':name,**data}

    async def execute(self,name,a,q,emit=None):
        output={};files=[];raw=[]
        try:
            if name in SOCIAL:
                # Platform router enforces read-only operations and keeps cookies in Tool Runtime.
                response=await self.api.client.post(self.api.base_url+'/v1/tool/'+name,json={**a,'requestId':q.session_id},headers=self.api.headers)
                response.raise_for_status();payload=response.json()
                if payload.get('code')!=200:raise ValueError('Social tool rejected request')
                return ToolReply(data={'tool':name,**payload['data']},failed=payload['data'].get('ok') is False,error=(payload['data'].get('error') or {}).get('message'),structured_output=payload)
            body=self.body(name,a,q)
            text='';code='';conclusion='';final=False;done=False
            research=ResearchResult(a.get('query',''))
            async with self.api.gate,asyncio.timeout(self.api.timeout_for(name)):
                async with self.api.client.stream('POST',self.api.base_url+'/v1/tool/'+REMOTE[name],json=body,
                      headers={**(self.api.resources.scope_headers(q.visitor_id,q.session_id) if getattr(self.api,'resources',None) else self.api.headers),'Accept':'text/event-stream'},timeout=self.api.timeout_for(name)) as response:
                    async for event in events(response):
                        if event is None:done=True;break
                        raw.append(event)
                        if isinstance(event.get('data'),dict) and event['data'].get('error'):raise ValueError('Analysis stream reported failure')
                        if event.get('error') or event.get('success') is False or event.get('code') in (400,403,500,502,504):
                            raise ValueError('Tool stream reported failure')
                        for f in event.get('fileInfo') or event.get('file_info') or []:
                            if isinstance(f,dict) and f not in files:files.append(f)
                        if name=='deep_search':
                            research.record(event);text=research.answer
                            if event.get('isFinal'):final=True
                            payload=dict(event)
                            payload['searchFinish']=event.get('messageType')!='extend'
                            kind='deep_search'
                            output={'query':research.query,'answer_summary':text[:2000],'stages_json':encode(research.stages())}
                        elif name=='multimodalagent_tool':
                            if event.get('stage'):
                                if event['stage']=='error':raise ValueError('MRAG stage error')
                                final=final or bool(event.get('isFinal')) or event['stage']=='final'
                                if emit:await emit('markdown',{'stage':event['stage'],'stageData':event,'isFinal':False})
                                continue
                            choices=event.get('choices') or []
                            if not choices:raise ValueError('MRAG chunk has no choices')
                            choice=choices[0];delta=(choice.get('delta') or {}).get('content') or ''
                            reason=choice.get('finishReason') or choice.get('finish_reason')
                            if reason=='error':raise ValueError('MRAG service reported error')
                            text+=delta;final=final or bool(reason)
                            payload={'data':text if final else delta,'isFinal':final};kind='markdown'
                            output={'summary':text[:2000],'markdown_content':text}
                        else:
                            delta=event.get('data') or event.get('content') or ''
                            if not isinstance(delta,str):delta=encode(delta)
                            if delta.strip():text+=delta+('' if delta.endswith('\n') else '\n')
                            if event.get('isFinal'):
                                conclusion=event.get('codeOutput') or event.get('content') or delta
                                if conclusion and conclusion not in text:text+='\n'+conclusion+'\n'
                                final=True
                            code=event.get('code') if isinstance(event.get('code'),str) else code
                            payload={**event,'data':text if event.get('isFinal') else delta}
                            kind='code' if name=='code_interpreter' else 'data_analysis'
                            output={'code_output':conclusion or text,'content':text,'code':code,'explain':event.get('explain')} if name=='code_interpreter' else {'task':a.get('task'),'summary':text[:2000],'content':text}
                        if emit:await emit(kind,payload)
            if not done or not final or not text.strip():raise ValueError('Tool stream ended without a complete result')
            if name=='deep_search':
                filename=report_name(a.get('reportFileName'))
                files.append(await self.upload(q,filename.rsplit('.',1)[0]+'_search_result.txt',encode(research.results),'DeepSearch检索结果'))
                files.append(await self.upload(q,filename,text,'DeepSearch研究报告'))
                data=research.observation(files)
            else:
                if name=='multimodalagent_tool':files.append(await self.upload(q,'知识检索报告.md',text,'多模态知识检索'))
                data={'tool':name,'ok':True,'content':text,'produced_files':[{'file_name':f['fileName'],'url':f.get('domainUrl') or f.get('downloadUrl')} for f in files]}
            return ToolReply(data=data,files=files,structured_output=output)
        except asyncio.CancelledError:raise
        except Exception as exc:
            timed=isinstance(exc,(TimeoutError,httpx.TimeoutException))
            # Preserve acquired evidence and intermediate files even on failure, never fake a final report.
            if name=='deep_search':output={'query':a.get('query'),'answer_summary':research.answer[:2000] if 'research' in locals() else '',
                                           'stages_json':encode(research.stages()) if 'research' in locals() else '[]'}
            return ToolReply(failed=True,error=name+' '+('执行超时' if timed else '执行失败：'+type(exc).__name__),timed_out=timed,files=files,structured_output=output)

    def body(self,name,a,q):
        if name=='deep_search':return {'request_id':q.session_id,'query':a.get('query',''),'report_file_name':report_name(a.get('reportFileName')),
                                      'search_engines':list(getattr(self.settings,'deepsearch_engines',())), 'stream':True}
        if name=='code_interpreter':return {'requestId':q.session_id,'task':a.get('task'),'fileName':report_name(a.get('fileName'),'代码解释器输出.md'),
            'fileNames':[f.get('fileName') for f in q.session_files or [] if f.get('fileName')],'stream':True,'permissionProfile':a.get('permissionProfile','analysis')}
        if name=='data_analysis':return {'request_id':q.session_id,'task':a.get('task',''),'report_file_name':report_name(a.get('reportFileName'),'数据分析报告.md'),
            'modelCodeList':list(getattr(self.settings,'analysis_models',())) or ['modelCode'],'businessKnowledge':a.get('businessKnowledge',''),'stream':True}
        if name=='multimodalagent_tool':return {'requestId':q.session_id,'question':a.get('question') or a.get('query') or q.query,
            'kb_ids':list(getattr(self.settings,'mrag_kb_ids',())),'image_urls':a.get('image_urls') or []}
        raise ValueError('Unsupported research tool')
