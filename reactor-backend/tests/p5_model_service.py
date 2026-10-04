"""Test-only deterministic model/image endpoint. Production never imports this file."""
import base64
import io
import struct
import os
from fastapi import Request
from fastapi.responses import JSONResponse,Response
from PIL import Image
from p3_model_service import app
from reactor_backend.models.types import encode

requests=[]

def png(color):
    output=io.BytesIO();Image.new('RGB',(96,64),color).save(output,format='PNG');return base64.b64encode(output.getvalue()).decode()

@app.post('/v1/images/generations')
async def images(request:Request):
    body=await request.json();requests.append({'path':'generations','body':body})
    if 'fallback' in body['prompt']:return JSONResponse({'error':'isolated failure'},status_code=503)
    return {'data':[{'b64_json':png('teal')}]}
@app.post('/v1/images/edits')
async def edits(request:Request):
    form=await request.form();values={k:[] for k in ('image','image[]','mask')}
    for k,v in form.multi_items():
        if hasattr(v,'read'):values[k].append({'name':v.filename,'size':len(await v.read())})
    requests.append({'path':'edits','body':{k:v for k,v in form.items() if not hasattr(v,'read')},'files':values})
    if 'fallback' in form['prompt']:return JSONResponse({'error':'isolated failure'},status_code=503)
    return {'data':[{'b64_json':png('coral')}]}
# Prepend override: the image chat fallback must be a real HTTP request, not a fake
# gateway result. Non-image chat uses the prior deterministic ReAct endpoint.
original=next(r.endpoint for r in app.routes if r.path=='/v1/chat/completions')
async def chat(request:Request):
    body=await request.json();prompt=encode(body.get('messages',[]))
    if 'fallback' in prompt:
        requests.append({'path':'chat','body':body});return JSONResponse({'choices':[{'message':{'content':'data:image/png;base64,'+png('gold')}}]})
    if 'P5_IMAGE_AGENT' in prompt:
        if not any(m.get('tool_call_id')=='p5-agent-image' for m in body['messages']):
            return JSONResponse({'model':'p5-local','choices':[{'message':{'role':'assistant','content':'','tool_calls':[{'id':'p5-agent-image','type':'function','function':{'name':'image_generation_tool','arguments':encode({'prompt':'P5 agent automatic attached reference','n':1})}}]},'finish_reason':'tool_calls'}]})
        return JSONResponse({'model':'p5-local','choices':[{'message':{'role':'assistant','content':'P5 agent image completed'},'finish_reason':'stop'}]})
    if 'P5_GENUI' in prompt and not any(m.get('role')=='tool' for m in body.get('messages',[])):
        tree={'root':{'kind':'Card','props':{'title':'P5 GenUI 真实用户流程'},'children':[{'kind':'Stat','nodeId':'title','props':{'value':'P5 交互与导出'}},{'kind':'Button','props':{'label':'发送后续消息','action':{'type':'send_message','payload':{'content':'P5 action verified'}}}},{'kind':'Model3D','props':{'src':'assets/模型.gltf'}},{'kind':'TableCell','props':{'value':'Unicode 嵌套文件与历史补丁'}}]}}
        mesh=base64.b64encode(struct.pack('<9f',-1,0,0,1,0,0,0,1.5,0)).decode()
        gltf=dict(asset={'version':'2.0'},scene=0,scenes=[{'nodes':[0]}],nodes=[{'mesh':0}],meshes=[{'primitives':[{'attributes':{'POSITION':0},'material':0}]}],buffers=[{'uri':'data:application/octet-stream;base64,'+mesh,'byteLength':36}],bufferViews=[{'buffer':0,'byteOffset':0,'byteLength':36,'target':34962}],accessors=[{'bufferView':0,'componentType':5126,'count':3,'type':'VEC3','min':[-1,0,0],'max':[1,1.5,0]}],materials=[{'pbrMetallicRoughness':{'baseColorFactor':[0,0.6,0.6,1],'metallicFactor':0,'roughnessFactor':.7},'doubleSided':True}])
        return JSONResponse({'model':'p5-local','choices':[{'message':{'role':'assistant','content':'','tool_calls':[{'id':'p5-html','type':'function','function':{'name':'workspace_write','arguments':encode({'path':'assets/canvas.html','content':'<!doctype html><meta charset="utf-8"><title>P5 Canvas</title><h1>P5 真实画布</h1><button onclick="this.textContent=\'交互成功\'">点击验收</button>'})}},{'id':'p5-mesh','type':'function','function':{'name':'workspace_write','arguments':encode({'path':'assets/模型.gltf','content':encode(gltf)})}},{'id':'p5-tree','type':'function','function':{'name':'emit_ui_tree','arguments':encode({'tree':tree,'canvas_id':'p5-canvas'})}}]},'finish_reason':'tool_calls'}]})
    if 'P5_GENUI' in prompt and any(m.get('role')=='tool' for m in body.get('messages',[])):
        if not any(m.get('tool_call_id')=='p5-canvas' for m in body['messages']):
            return JSONResponse({'model':'p5-local','choices':[{'message':{'role':'assistant','content':'','tool_calls':[{'id':'p5-canvas','type':'function','function':{'name':'canvas_publish','arguments':encode({'html_path':'assets/canvas.html','title':'P5 HTML Canvas'})}}]},'finish_reason':'tool_calls'}]})
        if not any(m.get('tool_call_id')=='p5-patch' for m in body['messages']):
            return JSONResponse({'model':'p5-local','choices':[{'message':{'role':'assistant','content':'','tool_calls':[{'id':'p5-patch','type':'function','function':{'name':'emit_ui_patch','arguments':encode({'canvas_id':'p5-canvas','seq':1,'patches':[{'op':'replace','path':'/root/children/0/props/value','value':'P5 补丁已生效'}]})}}]},'finish_reason':'tool_calls'}]})
        return JSONResponse({'model':'p5-local','choices':[{'message':{'role':'assistant','content':'P5 GenUI 与历史补丁已完成'},'finish_reason':'stop'}]})
    return await original(request)
for r in app.routes:
    if r.path=='/v1/chat/completions':r.endpoint=chat;r.app=__import__('starlette.routing',fromlist=['request_response']).request_response(chat)
@app.get('/p5/requests')
async def recorded():return requests

@app.get('/p5/skill-package')
async def skill_package():
    import zipfile
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as z:z.writestr('p5-url-package/SKILL.md','---\nname: p5-url-package\ndescription: Real HTTP import\n---\nUse the package.\n')
    return Response(output.getvalue(),media_type='application/zip')
