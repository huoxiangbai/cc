"""Deterministic upstream model ONLY for isolated P3 tests, using original tools."""
import json
from fastapi import FastAPI,Request
from fastapi.responses import StreamingResponse
import p2_model_service

app=FastAPI();requests=[]

@app.get('/test/requests')
async def captured():return requests

@app.post('/test/release/{key}')
async def release(key:str):return await p2_model_service.release(key)

@app.post('/v1/chat/completions')
async def complete(request:Request):
    body=await request.json();messages=body['messages'];requests.append(body)
    text='\n'.join(m['content'] if isinstance(m.get('content'),str) else json.dumps(m.get('content')) for m in messages)
    if 'P3' not in text:return await p2_model_service.complete(request)
    if body.get('tools'):
        query=next((m.get('content','') for m in messages if m['role']=='user' and isinstance(m.get('content'),str) and 'P3_' in m['content']),'')
        since=messages[next(i for i,m in enumerate(messages) if m.get('content')==query):]
        if any(m['role']=='tool' for m in since):message={'content':'P3 已完成真实工具执行；结果与文件以工具回执为准。'}
        else:
            tool,args=('code_interpreter',{'task':'P3_CODEACT: create a CSV with category A=30 and B=7.5, calculate their total using Python and deliver report','fileName':'代码分析.md'}) if 'P3_CODEACT' in query else ('code_execution',{'source':"from pathlib import Path\nimport csv\nrows = [('A',30),('B',7.5)]\nwith Path('sales.csv').open('w') as f:\n    w=csv.writer(f); w.writerow(['category','amount']);w.writerows(rows)\nprint(sum(r[1] for r in rows))"})
            message=p2_model_service.tool(tool,args,'p3-'+tool)
            if 'P3_DATA' in query:
                if '分析任务：' in query:
                    message=p2_model_service.tool('python_interpreter',{'code':"data = get_data('P3 查询各分类销售额')\nfinal_answer(data.to_markdown(index=False))"},'p3-analysis-code')
                else:message=p2_model_service.tool('data_analysis',{'task':'P3_DATA: 查询各分类销售额并交付来源报告','reportFileName':'分类销售分析.md'},'p3-data-analysis')
    else:
        if 'is_final' in text:content='{"is_final":true}'
        elif '高级、精确的 SQL' in text:content='P3销售汇总###SELECT `category`, SUM(`amount`) AS `total` FROM `sales-model` GROUP BY `category` ORDER BY `category`'
        elif 'relatedFlag' in text:content='{"relatedFlag":true,"columnIndexes":[1,2]}'
        elif '最小改动原则' in text:content='P3 查询各分类销售额'
        elif '业务数据解读' in text:content='1.按分类汇总销售额。2.关联category与amount。3.计算SUM并排序。'
        elif 'P3_CODEACT' in text:
            content="Task: compute sales\nThought: execute real Python and produce the CSV\nCode:\n<code>\nfrom pathlib import Path\nrows = [('A',30),('B',7.5)]\nPath(build_output_path('codeact-sales.csv')).write_text('category,amount\\nA,30\\nB,7.5\\n')\nprint(sum(r[1] for r in rows))\n</code>"
        else:content='P3 fixture extraction; sources are the attached page.'
        message={'role':'assistant','content':content}
    finish='tool_calls' if message.get('tool_calls') else 'stop'
    if not body.get('stream'):return {'model':'p3-fixture','choices':[{'message':message,'finish_reason':finish}],'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30}}
    async def stream():
        delta=dict(message)
        if delta.get('tool_calls'):
            delta['tool_calls']=[{**c,'index':i} for i,c in enumerate(delta['tool_calls'])]
        yield 'data:'+json.dumps({'model':'p3-fixture','choices':[{'delta':delta,'finish_reason':None}]},ensure_ascii=False)+'\n\n'
        yield 'data:'+json.dumps({'model':'p3-fixture','choices':[{'delta':{},'finish_reason':finish}],'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30}})+'\n\n'
        yield 'data:[DONE]\n\n'
    return StreamingResponse(stream(),media_type='text/event-stream')
