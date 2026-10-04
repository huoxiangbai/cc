import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
import pytest
import httpx
from reactor_backend.bootstrap.app import create_app
from reactor_backend.bootstrap.config import Settings
from reactor_backend.delivery.genui_export import pdf,docx,contents
from reactor_backend.adapters.image_gateway import size_value,tier,extract
from reactor_backend.delivery.genui_tools import execute
from reactor_backend.projection.genui import recover
from test_contracts import MemoryLedger,FixedModel,FixedTools

TREE={'root':{'kind':'Card','children':[{'kind':'Stat','props':{'label':'报告','value':'P5 迁移验收'}},{'kind':'TableCell','props':{'value':'独立导出内容 Unicode 正确'}},{'kind':'Table','props':{'headers':['类型','结果']},'children':[{'kind':'TableRow','children':[{'kind':'TableCell','props':{'value':'PDF'}},{'kind':'TableCell','props':{'value':'可读内容'}}]}]},{'kind':'Model3D','props':{'src':'模型.glb'}},{'kind':'Button','props':{'label':'继续'}}]}}

def test_export_real_content_and_deck_page_breaks():
    from pypdf import PdfReader
    from docx import Document
    raw=pdf(TREE);reader=PdfReader(io.BytesIO(raw));assert len(reader.pages)==1
    assert 'P5' in reader.pages[0].extract_text();assert '迁移验收' in reader.pages[0].extract_text()
    document=Document(io.BytesIO(docx(TREE)));text='\n'.join(p.text for p in document.paragraphs)
    assert '独立导出内容 Unicode 正确' in text and '类型 | 结果' in text and '[Model3D] 模型.glb' in text
    deck={'root':{'kind':'SlideDeck','children':[{'kind':'Slide','props':{'title':'One'}},{'kind':'Slide','props':{'title':'Two'}}]}}
    assert len(PdfReader(io.BytesIO(pdf(deck,'deck'))).pages)==2
    assert b'w:type="page"' in zipfile.ZipFile(io.BytesIO(docx(deck,'deck'))).read('word/document.xml')

@pytest.mark.parametrize('raw',['tree',None,{'root':{'kind':'Card','children':['invalid']}},{'root':{'kind':'Unknown'}}])
def test_export_rejects_invalid_tree(raw):
    with pytest.raises(ValueError):pdf(raw)

async def test_genui_tools_are_typed_and_replayable():
    reply=await execute(None,'emit_ui_tree',{'tree':json.dumps(TREE),'canvas_id':' canvas '})
    assert reply.data['canvasId']=='canvas' and json.loads(reply.structured_output['tree_json'])['root']['kind']=='Card'
    event=recover({'tool_call_id':'real-call','tool_name':'emit_ui_tree','structured_output':reply.structured_output},{})
    assert event[0]=='ui_tree' and event[1]['tree']['root']['kind']=='Card'
    patch=await execute(None,'emit_ui_patch',{'canvas_id':'canvas','seq':2,'patches':[{'op':'replace','path':'/root/children/0/props/value','value':'Updated'}]})
    assert patch.data['patchCount']==1 and patch.structured_output['seq']==2
    with pytest.raises(ValueError):await execute(None,'emit_ui_patch',{'patches':[{'op':'move','path':'/root'}]})
    components=await execute(None,'list_ui_components',{})
    assert components.data['rules'] and components.data['components']

@pytest.mark.parametrize('prompt,result',[('portrait 4K','2160x3840'),('logo','1024x1024'),('banner','1536x1024'),('portrait 1080p','1152x2048'),('513x999','512x1000')])
def test_original_image_size_inference(prompt,result):assert size_value(None,prompt)==result

@pytest.mark.parametrize('size',['1025x1024','255x1024','5000x1024','1:1','-1x1'])
def test_original_image_size_rejection(size):
    with pytest.raises(ValueError):size_value(size,'')

def test_image_response_shapes_and_dedupe():
    assert extract(json.dumps({'data':[{'url':'https://a/x.png'},{'url':'https://a/x.png'}]}))==['https://a/x.png']
    assert extract(json.dumps({'output':[{'type':'image_generation_call','result':'AAAA'}]}))==['data:image/png;base64,AAAA']
    assert extract(json.dumps({'choices':[{'message':{'content':'![x](https://a/x.png)'}}]}))==['https://a/x.png']

async def test_original_route_manifest_and_admin_auth(tmp_path):
    app=create_app(Settings('unused','unused',tmp_path,private_tool_gateway=True,tool_service_token='t'*32),ledger=MemoryLedger(),model=FixedModel([]),tools=FixedTools())
    def normalize(path):return __import__('re').sub(r'\{[^}]+\}','{}',path)
    original=json.loads((Path(__file__).resolve().parents[2]/'docs/python-migration/fixtures/runtime-routes.json').read_text())
    # The audit manifest is the authority; all routes must have the original method.
    routes={(normalize(r.path),m) for r in app.routes for m in getattr(r,'methods',[])}
    entries=original if isinstance(original,list) else original.get('routes',[])
    for item in entries:
        methods=item.get('verbs')
        if not methods:methods=['GET','POST','PUT','DELETE','PATCH','HEAD','OPTIONS']
        for path in item['paths']:
            for method in methods:assert (normalize(path),method) in routes,(item,method)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        denied=await client.get('/api/v1/admin/admin-user/query-all',headers={'Origin':Settings('unused','unused',tmp_path).cors_origins[0]})
        assert denied.headers['access-control-allow-origin']==Settings('unused','unused',tmp_path).cors_origins[0]
        for path in ('ai-client-api/query-all','ai-client-model/query-all','admin-user/query-all','skills/list','sub-agent-definitions/query-list','featured-conversations/query-list'):
            response=await client.request('POST' if path.endswith('query-list') and path.startswith('featured') else 'GET','/api/v1/admin/'+path)
            assert response.json()['code']=='0003'
        response=await client.post('/api/agent/genui/export/pdf',json={'tree':TREE})
        assert response.status_code==200 and response.content.startswith(b'%PDF')
