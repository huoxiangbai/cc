"""The five Java native WebSearch channels. Skill/MCP channels stay separate."""
import asyncio
import re
import time
from urllib.parse import urlsplit
from reactor_backend.models.types import ToolReply

DEFAULTS={'grok':('https://api.x.ai/v1/chat/completions','grok-4'),
          'gpt':('https://api.openai.com/v1/responses','gpt-4.1'),
          'exa':('https://api.exa.ai/search',None),'tavily':('https://api.tavily.com/search',None),
          'brave':('https://api.search.brave.com/res/v1/web/search',None)}


def citations(root):
    hits=[];texts=[]
    def visit(value):
        if isinstance(value,list):
            for x in value:visit(x)
        elif isinstance(value,dict):
            if value.get('type')=='url_citation' or any(k in value for k in ('url','source_url','link')):
                url=value.get('url') or value.get('source_url') or value.get('link')
                if url:hits.append({'title':value.get('title') or value.get('name') or url,'url':url,'snippet':value.get('snippet') or value.get('text')})
            if isinstance(value.get('text'),str):texts.append(value['text'])
            if isinstance(value.get('content'),str):texts.append(value['content'])
            for k,x in value.items():
                if k=='citations' and isinstance(x,list):
                    for c in x:
                        if isinstance(c,str):hits.append({'title':c,'url':c})
                visit(x)
    visit(root)
    summary=root.get('output_text') or '\n'.join(dict.fromkeys(texts))
    if not hits:
        hits=[{'title':t,'url':u} for t,u in re.findall(r'\[([^\]]+)\]\((https?://[^)]+)\)',summary)]
    if not hits:hits=[{'title':u,'url':u} for u in re.findall(r'https?://[^\s)>"\]]+',summary)]
    return hits,summary


class WebSearch:
    def __init__(self,client,config):self.client,self.config=client,config
    async def execute(self,a):
        start=time.monotonic();query=str(a.get('query') or '').strip()
        allowed=[str(v).lower().strip() for v in a.get('allowed_domains') or []];blocked=[str(v).lower().strip() for v in a.get('blocked_domains') or []]
        if len(query)<2 or allowed and blocked:return ToolReply(failed=True,error='WebSearch 失败：query 至少2个字符，且不能同时指定 allowed_domains 与 blocked_domains')
        mode=self.config.get('provider','auto').lower();mode={'xai':'grok','openai':'gpt'}.get(mode,mode)
        plans=[p for p in DEFAULTS if self.config.get(p,{}).get('api_key') and mode in ('auto',p)]
        errors=[]
        if not plans:return ToolReply(failed=True,error='WebSearch 未配置：需要 Grok/GPT/Exa/Tavily/Brave API key')
        for p in plans:
            try:
                hits,summary=await self.search(p,query,allowed,blocked)
                seen=set();rows=[]
                for h in hits:
                    u=h.get('url','');host=urlsplit(u).hostname or ''
                    if not u.startswith(('https://','http://')) or u in seen:continue
                    if allowed and not any(host==d or host.endswith('.'+d) for d in allowed):continue
                    if any(host==d or host.endswith('.'+d) for d in blocked):continue
                    seen.add(u);rows.append({k:v for k,v in h.items() if v})
                return ToolReply(data={'tool':'web_search','ok':True,'query':query,'provider':p,'durationSec':round(time.monotonic()-start,2),
                    'summary':summary,'hits':rows[:8],'reminder':'Cite sources with markdown hyperlinks in the final answer.'},structured_output={'provider':p,'hits':rows,'provider_failures':errors})
            except asyncio.CancelledError:raise
            except Exception as exc:errors.append({'provider':p,'error':type(exc).__name__})
        return ToolReply(failed=True,error='WebSearch 全部 provider 失败',data={'provider_failures':errors})
    async def search(self,p,q,allowed,blocked):
        cfg=self.config[p];url=cfg.get('url') or DEFAULTS[p][0];key=cfg['api_key']
        filtered=q+(' ('+' OR '.join('site:'+d for d in allowed)+')' if allowed else '')+' '.join(' -site:'+d for d in blocked)
        headers={'Authorization':'Bearer '+key};body={};method='POST';params=None
        if p=='grok':
            body={'model':cfg.get('model') or DEFAULTS[p][1],'temperature':0,'stream':False,'messages':[
                {'role':'system','content':'You are a web search assistant. Use live web search. Return concise findings with source titles and URLs as markdown links.'},
                {'role':'user','content':'Search the web and summarize results for: '+filtered}], 'tools':[{'type':'web_search'}],'tool_choice':'auto'}
            try:root=await self.request(method,url,headers,body)
            except Exception:
                body.pop('tools');body.pop('tool_choice');body['search_parameters']={'mode':'on','return_citations':True,'max_search_results':8}
                root=await self.request(method,url,headers,body)
            hits,summary=citations(root)
            if not hits and not summary:raise ValueError('Empty Grok result')
            return hits,summary
        if p=='gpt':
            tool={'type':'web_search_preview'}
            if allowed:tool['filters']={'allowed_domains':allowed}
            elif blocked:tool['filters']={'blocked_domains':blocked}
            body={'model':cfg.get('model') or DEFAULTS[p][1],'input':q,'tools':[tool]}
        if p=='exa':
            headers={'x-api-key':key};body={'query':q,'numResults':8,'useAutoprompt':True,'contents':{'text':{'maxCharacters':2000}}}
            if allowed:body['includeDomains']=allowed
            if blocked:body['excludeDomains']=blocked
        if p=='tavily':
            body={'query':q,'max_results':8,'search_depth':'basic','include_answer':False}
            if allowed:body['include_domains']=allowed
            if blocked:body['exclude_domains']=blocked
        if p=='brave':method='GET';headers={'X-Subscription-Token':key};params={'q':filtered,'count':8}
        root=await self.request(method,url,headers,body,params)
        if p=='gpt':
            hits,summary=citations(root)
            if not hits and not summary:raise ValueError('Empty GPT result')
            return hits,summary
        rows=(root.get('web') or {}).get('results',[]) if p=='brave' else root.get('results',[])
        return [{'title':r.get('title') or r.get('url'),'url':r.get('url'),
                 'snippet':str(r.get('text') or r.get('content') or r.get('description') or r.get('summary') or '')[:500]} for r in rows],None
    async def request(self,method,url,headers,body,params=None):
        response=await self.client.request(method,url,headers=headers,json=body if method=='POST' else None,params=params,timeout=60)
        response.raise_for_status();root=response.json()
        if root.get('error'):raise ValueError('Search provider error')
        return root
