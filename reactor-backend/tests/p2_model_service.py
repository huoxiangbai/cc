"""Isolated HTTP model fixture for P2 UI/TCP workflows; never imported by production."""
import asyncio
import json
from fastapi import FastAPI,Request
from fastapi.responses import StreamingResponse
import model_service

app=FastAPI();requests=[];barriers={}
QUESTIONS=[{'question':'选择报告方向？','header':'方向','options':[{'label':'研究','description':'研究报告'},{'label':'分析','description':'数据分析'}],'multiSelect':False}]


def tool(name,args,identifier):
    return {'content':'执行 '+name,'tool_calls':[{'id':identifier,'type':'function','function':{'name':name,'arguments':json.dumps(args,ensure_ascii=False)}}]}


@app.get('/test/requests')
async def captured():
    return requests


@app.post('/test/release/{key}')
async def release(key:str):
    barriers.setdefault(key,asyncio.Event()).set()
    return {'released':key}


@app.post('/v1/chat/completions')
async def complete(request:Request):
    body=await request.json();messages=body['messages'];requests.append(body)
    query=next((m.get('content') or '' for m in messages if m['role']=='user' and 'P2_' in (m.get('content') or '')),None)
    if query is None:return await model_service.complete(request)
    tools=[m for m in messages if m['role']=='tool'];count=len(tools)
    observations=[json.loads(m['content']) for m in tools if m.get('content','').startswith('{')]
    if 'P2_CHILD' in query:
        if not count:
            if query.split()[-1]=='restartbg':await barriers.setdefault('restartbg',asyncio.Event()).wait()
            else:await asyncio.sleep(.65)
            m=tool('text_processor',dict(operation='write',file_path='worker-'+query.split()[-1]+'.md',data='P2 真实子 Agent 工具产物\n'), 'p2-worker-write-'+query.split()[-1])
        else:
            guidance='；收到指导' if any('[User guidance]' in (x.get('content') or '') for x in messages) else ''
            m={'content':'子 Agent 已完成真实文件写入'+guidance}
    elif 'P2_ASK' in query:
        if not count:m=tool('AskUserQuestion',{'questions':QUESTIONS},'p2-ask')
        elif count==1:
            assert observations[-1].get('answers')
            m=tool('text_processor',dict(operation='write',file_path='回答报告.md',data='P2 用户回答：'+json.dumps(observations[-1]['answers'],ensure_ascii=False)), 'p2-ask-write')
        else:m={'content':'已按用户回答生成报告。'}
    elif 'P2_PLAN' in query:
        decisions=[o for o in observations if o.get('tool')=='ExitPlanMode']
        if not decisions:m=tool('ExitPlanMode',{'plan':'# P2 计划\n1. 用真实工具写报告\n2. 核实交付'},'p2-plan-1')
        elif not decisions[-1].get('approved'):
            m=tool('ExitPlanMode',{'plan':'# 修订计划\n采纳反馈：'+str(decisions[-1].get('feedback'))},'p2-plan-'+str(len(decisions)+1))
        elif tools[-1]['tool_call_id'].startswith('p2-plan-') and tools[-1]['tool_call_id']!='p2-plan-write':
            m=tool('text_processor',dict(operation='write',file_path='计划报告.md',data=decisions[-1]['plan']), 'p2-plan-write')
        else:m={'content':'已执行用户批准或编辑的计划，报告已写入。'}
    elif 'P2_STOP' in query:
        if not count:m=tool('TaskCreate',dict(subject='取消验证',description='只执行一次'), 'p2-stop-todo')
        else:await asyncio.sleep(5);m={'content':'迟到回复'}
    elif 'P2_BG' in query or 'P2_SYNC' in query or 'P2_MAIL' in query:
        if not count:
            m=tool('Agent',dict(description='实际后台文件任务',prompt='P2_CHILD '+query.split()[-1],run_in_background='P2_SYNC' not in query),'p2-agent')
        elif 'P2_MAIL' in query and count==1:
            receipt=observations[-1];m=tool('SendMessage',dict(to=receipt['agentId'],message='请采纳用户指导'),'p2-mail')
        elif 'P2_MAIL' in query and count==2:
            m=tool('TaskOutput',dict(task_id=observations[0]['task_id'],block=True,timeout=30000),'p2-output')
        else:m={'content':'根 Agent 已返回，后台任务将继续排空。'}
    elif 'P2_TODO' in query:
        actions=[('TaskCreate',dict(subject='收集',description='收集来源')),('TaskCreate',dict(subject='综合',description='综合来源')),
                 ('TaskUpdate',dict(taskId='2',status='in_progress',addBlockedBy=['1'])),('TaskList',{})]
        m=tool(*actions[count],identifier='p2-todo-'+str(count)) if count<len(actions) else {'content':'Todo 持久化与依赖已保存。'}
    else:m={'content':'P2 fixture direct result'}
    finish='tool_calls' if m.get('tool_calls') else 'stop'
    if not body.get('stream'):return {'model':'p2-fixed-upstream','choices':[{'message':m,'finish_reason':finish}]}
    async def chunks():
        delta={'content':m.get('content','')}
        if m.get('tool_calls'):
            delta['tool_calls']=[dict(index=i,**call) for i,call in enumerate(m['tool_calls'])]
        yield 'data:'+json.dumps({'model':'p2-fixed-upstream','choices':[{'delta':delta,'finish_reason':None}]},ensure_ascii=False)+'\n\n'
        yield 'data:'+json.dumps({'choices':[{'delta':{},'finish_reason':finish}],'usage':dict(prompt_tokens=30,completion_tokens=15,total_tokens=45)})+'\n\n'
        yield 'data:[DONE]\n\n'
    return StreamingResponse(chunks(),media_type='text/event-stream')
