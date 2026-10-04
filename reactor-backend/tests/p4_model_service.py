"""P4 deterministic HTTP model; all tools/providers/persistence remain real adapters."""
import json
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse,StreamingResponse
import p3_model_service
from p2_model_service import tool

app=FastAPI();requests=[]

@app.get('/test/requests')
async def captured():return requests+p3_model_service.requests

@app.post('/test/release/{key}')
async def release(key:str):return await p3_model_service.release(key)

@app.post('/v1/chat/completions')
async def complete(request:Request):
    body=await request.json();messages=body['messages'];requests.append(body)
    system=messages[0].get('content','');latest=next((m.get('content','') for m in reversed(messages) if m['role']=='user'),'')
    if not isinstance(system,str):system=json.dumps(system,ensure_ascii=False)
    if not isinstance(latest,str):latest=json.dumps(latest,ensure_ascii=False)
    if system.startswith('Create a factual conversation checkpoint'):
        if 'P4_PERMANENT_FAIL' in str(messages):return JSONResponse({'error':{'message':'unauthorized test fixture'}},status_code=401)
        if 'P4_TRANSIENT_FAIL' in str(messages):m={'content':''}
        else:m={'content':'历史用户决策：保留原表关系，继续任务；来源文件 report.csv。'}
    elif latest.startswith('Review this conversation'):
        m={'content':'记忆已保存。'} if messages[-1]['role']=='tool' else tool('memory',{'action':'add','target':'curated','content':'P4 fork retained durable decisions'},'p4-fork-write')
    elif any(x.get('tool_call_id')=='p4-fork-write' for x in messages[-4:]):m={'content':'记忆已保存。'}
    elif latest.startswith('P4_'):
        after=messages[max(i for i,m in enumerate(messages) if m.get('content')==latest):]
        observations=[m for m in after if m['role']=='tool'];n=len(observations)
        if latest.startswith('P4_MEMORY'):
            m=tool('memory',{'action':'add','target':'user','content':'P4 用户偏好中文报告'},'p4-memory') if n==0 else {'content':'记忆已实际持久化。'}
        elif latest.startswith('P4_SKILL'):
            actions=[('skill_tool',{'skill_name':'skill-creator'}),('workspace_write',{'path':'skills/p4-created/SKILL.md','content':'---\nname: p4-created\ndescription: isolated created skill\n---\n# 真正会话技能\n'}),('bash',{'command':'PYTHONPATH=skills/skill-creator '+latest.split(' ',1)[1]+' skills/skill-creator/scripts/package_skill.py skills/p4-created .'}),('workspace_read',{'path':'skills/p4-created/SKILL.md'})]
            m=tool(*actions[n],identifier='p4-skill-'+str(n)) if n<len(actions) else {'content':'真实原 Skill Creator 脚本已打包会话技能。'}
        elif latest.startswith('P4_MCP'):
            names=['mcp__P4_'+k+'__original_echo_' for k in ('sse','stdio','streamable_http')]
            actions=[('ToolSearch',{'query':'select:'+','.join(names),'max_results':10})]+[(name,{'text':'真实P4参数-'+str(i)}) for i,name in enumerate(names)]+[('ListMcpResources',{}),('ReadMcpResource',{'server':'p4-sse','uri':'p4://manual'})]
            m=tool(*actions[n],identifier='p4-mcp-'+str(n)) if n<len(actions) else {'content':'三个真实 MCP 端点已执行并读取资源。'}
        elif latest.startswith('P4_SEARCH'):
            m=tool('session_search',{'query':'旧轮证据','scope':'session'},'p4-search') if n==0 else {'content':'已检索实际工作记忆。'}
        else:m={'content':'已读取旧工作记忆，继续本轮。'}
    else:return await p3_model_service.complete(request)
    finish='tool_calls' if m.get('tool_calls') else 'stop'
    if not body.get('stream'):return {'model':'p4-fixture','choices':[{'message':m,'finish_reason':finish}]}
    async def stream():
        delta=dict(m)
        if delta.get('tool_calls'):delta['tool_calls']=[dict(index=i,**call) for i,call in enumerate(delta['tool_calls'])]
        yield 'data:'+json.dumps({'model':'p4-fixture','choices':[{'delta':delta,'finish_reason':None}]},ensure_ascii=False)+'\n\n'
        yield 'data:'+json.dumps({'choices':[{'delta':{},'finish_reason':finish}],'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30}})+'\n\n'
        yield 'data:[DONE]\n\n'
    return StreamingResponse(stream(),media_type='text/event-stream')
