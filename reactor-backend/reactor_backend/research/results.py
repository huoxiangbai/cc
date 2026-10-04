"""DeepSearch typed stages and compact evidence observation matching Java storage."""
import re


def report_name(value,default='深度搜索报告.md'):
    name=re.sub(r'[<>:"|?*\x00-\x1f]','',str(value or '').strip().replace('/','_').replace('\\','_'))
    if name and not name.lower().endswith('.md'):name+='.md'
    return name if name and len(name)<=20 else default


class ResearchResult:
    def __init__(self,query):
        self.query=query;self.queries=[];self.results={};self.chapters={};self.answer=''
        self.raw=[]
    def record(self,event):
        self.raw.append(dict(event))
        self.query=event.get('query') or self.query
        sr=event.get('searchResult') or {}
        for q in sr.get('query') or []:
            if q not in self.queries:self.queries.append(q)
        for q,docs in zip(sr.get('query') or [],sr.get('docs') or []):
            current=self.results.setdefault(q,[])
            for doc in docs or []:
                key=doc.get('link') or doc.get('title') or doc.get('content')
                if key not in [d.get('link') or d.get('title') or d.get('content') for d in current]:current.append(dict(doc))
        if event.get('messageType')=='chapter_summary':
            self.chapters[event.get('chapterId') or str(event.get('chapterOrder'))]=dict(event)
        if event.get('messageType')=='report':
            if event.get('isFinal'):self.answer=event.get('answer') or self.answer
            else:self.answer+=event.get('answer') or ''
    def stages(self):
        stages=[{'stage':'extend','queries':self.queries}]
        rows=[{'query':q,'docs':[dict(title=d.get('title'),link=d.get('link'),summary=d.get('content') or d.get('summary')) for d in ds]} for q,ds in self.results.items()]
        stages.append({'stage':'search','results':rows})
        for c in sorted(self.chapters.values(),key=lambda c:c.get('chapterOrder') or 0):
            stages.append({'stage':'chapter_summary',**{k:c.get(k) for k in ('chapterId','chapterTitle','chapterContent','chapterOrder','chapterSummary')},'queries':(c.get('searchResult') or {}).get('query') or [],'results':[]})
        stages.append({'stage':'report','answer':self.answer})
        return stages+[{"stage":"tool_event","event":e} for e in self.raw]
    def observation(self,files):
        return {'tool':'deep_search','ok':True,'query':self.query,'queries':self.queries,
                'search_results':[{'query':q,'docs':[{'title':d.get('title'),'link':d.get('link'),'summary':str(d.get('content') or d.get('summary') or '')[:180]} for d in ds[:3]]} for q,ds in self.results.items()],
                'chapters':[{'chapterId':c.get('chapterId'),'chapterTitle':c.get('chapterTitle'),'chapterSummary':str(c.get('chapterSummary') or '')[:400]} for c in self.chapters.values()],
                'answer_summary':self.answer[:2000],
                'produced_files':[{'file_name':f['fileName'],'url':f.get('domainUrl') or f.get('downloadUrl')} for f in files]}
