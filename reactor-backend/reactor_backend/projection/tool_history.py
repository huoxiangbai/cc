"""Original rich-tool read-side payloads; does not enable their execution."""
from reactor_backend.projection.genui import decode,recover
from reactor_backend.delivery.artifacts import artifact_ref

from reactor_backend.models.tool_outputs import OUTPUT_TABLES


def file_infos(artifacts):
    result=[]
    for a in artifacts:
        ref=artifact_ref(a)
        info=dict(fileName=a['file_name'],downloadUrl=a.get('download_url'),previewUrl=a.get('preview_url'),
                  ossUrl=a.get('download_url'),domainUrl=a.get('preview_url'),missing=False)
        for key in ('relativePath','originFileName'):
            if ref.get(key): info[key]=ref[key]
        if a.get('file_size') is not None: info['fileSize']=a['file_size']
        result.append(info)
    return result


def project(t,params,artifacts):
    """None means generic tool; [] is the original no-stage deep_search behavior."""
    genui=recover(t,params)
    if genui: return [(*genui,artifacts)]
    name=t['tool_name'];o=t.get('structured_output') or {}
    observation=t.get('llm_oberserve') or ''
    payload={'isFinal':True};files=file_infos(artifacts)
    def text(key): return o.get(key) or ''
    def with_files(kind):
        payload['fileInfo']=files
        return [(kind,payload,artifacts)]
    if name=='code_interpreter':
        data=text('code_output')
        if not data.strip(): data=observation
        payload.update(codeOutput=data,data=data)
        for key in ('content','code','explain'):
            if text(key).strip(): payload[key]=o[key]
        return with_files('code')
    if name=='data_analysis':
        data=text('content')
        if not data.strip(): data=observation
        payload.update(task=text('task'),data=data)
        return with_files('data_analysis')
    if name=='multimodalagent_tool':
        data=text('markdown_content')
        if not data.strip(): data=observation
        payload['data']=data
        if text('summary').strip(): payload['summary']=o['summary']
        return with_files('markdown')
    if name=='canvas_publish':
        payload.update(fileType='html',command='发布画布')
        for column,key in [('title','title'),('primary_file_name','primaryFileName'),('preview_url','previewUrl'),('download_url','downloadUrl')]:
            if text(column).strip(): payload[key]=o[column]
        return with_files('html')
    if name=='image_generation_tool':
        events=[]
        if files: events.append(('file',{'command':'生成图片','fileInfo':files},artifacts))
        summary=text('summary')
        if not summary.strip(): summary=observation
        events.append(('tool_result',{'toolName':name,'toolParam':params,'toolResult':summary,'toolCallId':t['tool_call_id']},[]))
        return events
    if name.lower()=='askuserquestion':
        obs=decode(observation,{})
        if not isinstance(obs,dict): obs={}
        persisted=t.get('persisted_question') or {}
        payload={'messageType':'ask_user_question','input':params}
        questions=decode(persisted.get('questions_json'))
        if questions is None: questions=obs.get('questions',params.get('questions'))
        if questions is not None: payload['questions']=questions
        answers=decode(persisted.get('answers_json'))
        if answers is None: answers=obs.get('answers')
        if isinstance(answers,dict): payload['answers']=answers
        status=persisted.get('status')
        client_status='answered' if isinstance(answers,dict) else 'pending'
        if status:
            client_status='answered' if status in ('ANSWERED','RESUMING','RESUME_PENDING') else 'timeout' if status=='TIMEOUT' else 'cancelled' if status in ('CANCELLED','FAILED') else 'pending'
            payload['persistenceStatus']=status
        payload['status']=client_status
        question_id=obs.get('questionId') or persisted.get('question_id')
        if question_id: payload['questionId']=question_id
        return [('ask_user_question',payload,artifacts)]
    if name=='deep_search':
        stages=decode(o.get('stages_json'),[])
        return deep_search(o.get('query'),stages,artifacts)
    return None


def deep_search(query,stages,artifacts):
    chapters=[dict(chapterId=s.get('chapterId'),chapterTitle=s.get('chapterTitle'),chapterContent=s.get('chapterContent'),chapterOrder=s.get('chapterOrder'),queries=s.get('queries') or []) for s in stages if s and s.get('stage')=='chapter_summary']
    events=[]
    def results(stage):
        queries,docs=[],[]
        for item in stage.get('results') or []:
            if not item: continue
            queries.append(item.get('query') or '')
            row=[]
            for doc in item.get('docs') or []:
                if not doc: continue
                d={'title':doc.get('title') or '', 'link':doc.get('link') or ''}
                if (doc.get('summary') or '').strip(): d['content']=doc['summary']
                row.append(d)
            docs.append(row)
        return queries,docs
    for stage in stages:
        if not stage: continue
        kind=stage.get('stage')
        if kind not in ('extend','search','chapter_summary','report'): continue
        p=dict(messageType=kind,isFinal=True,query=query)
        refs=[]
        if kind=='extend':
            p.update(searchFinish=False,searchResult=dict(query=stage.get('queries') or [],docs=[],chapters=chapters))
        elif kind=='search':
            q,d=results(stage)
            p.update(searchFinish=True,searchResult=dict(query=q,docs=d,chapters=chapters))
        elif kind=='chapter_summary':
            p.update(searchFinish=True,chapterId=stage.get('chapterId') or '',chapterTitle=stage.get('chapterTitle') or '',
                     chapterContent=stage.get('chapterContent') if stage.get('chapterContent') is not None else stage.get('chapterTitle'),
                     chapterOrder=stage.get('chapterOrder'),chapterSummary=stage.get('chapterSummary') or '',answer=stage.get('chapterSummary') or '')
            q,d=results(stage);queries=list(stage.get('queries') or [])
            for item in q:
                if item not in queries: queries.append(item)
            p['searchResult']=dict(query=queries,docs=d)
        else:
            p['answer']=stage.get('answer') or ''
            refs=[a for a in artifacts if a.get('file_name') and not a['file_name'].lower().endswith('_search_result.txt')]
        events.append(('deep_search',p,refs))
    return events
