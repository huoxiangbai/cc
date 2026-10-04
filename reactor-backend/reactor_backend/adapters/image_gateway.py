"""Java Micu/OpenAI-compatible gateway, including Grok, masks and chat fallback."""
import asyncio
import base64
import json
import re
from urllib.parse import urlsplit,quote,unquote
import httpx

RETRY={0,408,409,425,429,500,502,503,504,520,521,522,523,524,525,527}
FALLBACK={0,408,500,502,503,504,520,521,522,523,524,525,527}
RATIOS=['1:1','16:9','9:16','4:3','3:4','3:2','2:3','2:1','1:2']
MAX_RESPONSE=25*1024*1024

def mime(raw):
    if raw.startswith(b'\xff\xd8'):return 'image/jpeg'
    if raw.startswith(b'GIF'):return 'image/gif'
    if raw.startswith(b'RIFF'):return 'image/webp'
    return 'image/png'

def data_url(raw,kind):return 'data:'+kind+';base64,'+base64.b64encode(raw).decode()

def decode(value):
    if value.startswith('data:'):
        m=re.fullmatch(r'data:([^;,]+);base64,(.+)',value,re.S|re.I)
        if not m:raise ValueError('无效图片 data URL')
        return base64.b64decode(re.sub(r'\s','',m[2]),validate=True),m[1]
    return base64.b64decode(value,validate=True),'image/png'

def size_value(raw,prompt):
    if raw and str(raw).strip():value=str(raw).strip().lower()
    else:
        p=prompt.lower();m=re.search(r'(\d{3,4})\s*[x×]\s*(\d{3,4})',p)
        value=None
        if m:
            w,h=(max(16,int(int(v)/8+.5)*8) for v in m.groups())
            if 256<=w<=4096 and 256<=h<=4096:value=f'{w}x{h}'
        vertical=any(k in p for k in ('9:16','竖屏','竖版','vertical','portrait','手机壁纸'))
        horizontal=any(k in p for k in ('16:9','横屏','横版','landscape','wallpaper','壁纸','banner','封面'))
        square=any(k in p for k in ('正方形','square','avatar','头像','logo','icon'))
        if not value:
            if re.search(r'\b4k\b',p) or 'uhd' in p or '超高清' in p:value='2160x3840' if vertical else '3840x2160'
            elif re.search(r'\b2k\b',p) or any(k in p for k in ('1080p','fullhd','full hd')):value='1152x2048' if vertical else '2048x1152'
            else:value='1024x1024' if square else '1024x1536' if vertical else '1536x1024' if horizontal else '1024x1024'
    m=re.fullmatch(r'(\d+)x(\d+)',value)
    if not m:raise ValueError('size 格式错误，必须是 WxH，收到 '+value)
    w,h=map(int,m.groups())
    if not w or not h:raise ValueError('size W/H 必须为正数')
    if min(w,h)<256 or max(w,h)>4096:raise ValueError('size 边长必须在 256-4096')
    if w%8 or h%8:raise ValueError('size W/H 必须是 8 的倍数')
    return f'{w}x{h}'

def tier(size):
    edge=max(map(int,size.split('x')))
    return 'small' if edge<1024 else '1k' if edge<1600 else '2k' if edge<3000 else '4k'

def extract(text):
    output=[]
    def from_text(s):
        output.extend(m[0] for m in re.finditer(r'data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+',s,re.I))
        output.extend(m[1] for m in re.finditer(r'!\[[^\]]*\]\((https?://[^)\s]+)\)',s,re.I))
        output.extend(m[0] for m in re.finditer(r'https?://[^\s"\'<> )]+\.(?:png|jpe?g|gif|webp)(?:\?[^\s"\'<>)]*)?',s,re.I))
    try:obj=json.loads(text)
    except ValueError:obj={}
    if isinstance(obj,dict):
        for item in obj.get('data') or []:
            if isinstance(item,dict):
                if item.get('b64_json'):output.append('data:image/png;base64,'+item['b64_json'])
                elif item.get('url'):output.append(item['url'])
        for item in obj.get('output') or []:
            if isinstance(item,dict) and item.get('type')=='image_generation_call' and item.get('result'):
                value=item['result'];output.append(value if value.startswith('data:') else 'data:image/png;base64,'+value)
        choices=obj.get('choices') or []
        if choices:
            content=(choices[0].get('message') or {}).get('content')
            if isinstance(content,str):from_text(content)
            elif isinstance(content,list):
                for part in content:
                    if (part.get('image_url') or {}).get('url'):output.append(part['image_url']['url'])
                    elif part.get('text'):from_text(part['text'])
    if not output:from_text(text)
    unique={}
    for value in output:unique.setdefault(value[:120] if value.startswith('data:') else value,value)
    return list(unique.values())

class ImageGateway:
    def __init__(self,client,api,config):self.client,self.api,self.config=client,api,config
    async def bytes(self,url,limit,headers=None):
        async with self.client.stream('GET',url,headers=headers or {},timeout=900,follow_redirects=True) as response:
            response.raise_for_status();raw=bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw)>limit:raise ValueError('图片内容超过大小限制')
            return bytes(raw),response.headers.get('content-type','').split(';')[0]
    async def reference(self,reference,query,label):
        value=str(reference or '').strip()
        if not value:raise ValueError(label+' 为空')
        if value.startswith('data:'):raw,kind=decode(value)
        else:
            if value.startswith(('/preview/','/download/')):value=self.api.base_url+'/v1/file_tool'+value
            elif not value.startswith(('http://','https://')):value=self.api.base_url+'/v1/file_tool/preview/'+quote(query.session_id,safe='')+'/'+quote(value.replace('\\','/').rsplit('/',1)[-1],safe='')
            path=unquote(urlsplit(value).path);headers={}
            if '/file_tool/preview/' in path or '/file_tool/download/' in path:
                # A caller cannot use a private reference from another namespace, even
                # when its host is rewritten to the trusted internal Tool service.
                suffix=re.split(r'/file_tool/(?:preview|download)/',path,1)[1];key=suffix.split('/',1)[0]
                if getattr(self.api,'resources',None):await self.api.resources.require(query.visitor_id,'file_scope',key)
                action='preview' if '/preview/' in path else 'download'
                value=self.api.base_url+'/v1/file_tool/'+action+'/'+quote(key,safe='')+'/'+quote(suffix.split('/',1)[1],safe='/')
                headers=self.api.headers
            elif getattr(self.api,'resources',None):
                from hashlib import sha256
                owner=await self.api.resources.owner('document_url',sha256(value.encode()).hexdigest())
                if owner and owner!=query.visitor_id:raise PermissionError('无权访问图片引用')
            raw,kind=await self.bytes(value,4*1024*1024,headers)
        if not raw or len(raw)>4*1024*1024:raise ValueError(label+' 内容为空或超过单图 4MB 上限')
        if not kind.startswith('image/'):kind=mime(raw)
        return (label+'.png',raw,kind)
    async def call(self,base,key,path,body,images,aggressive,notes):
        attempts=3 if aggressive else 2;delays=[2,8] if aggressive else [1]
        status=0;raw=''
        for attempt in range(attempts):
            try:
                kwargs={'files':images,'data':{k:str(v) for k,v in body.items()}} if images else {'json':body}
                async with self.client.stream('POST',base.rstrip('/')+path,headers={'Authorization':'Bearer '+key,'Accept':'application/json'},timeout=httpx.Timeout(900,connect=60),**kwargs) as response:
                    status=response.status_code;content=bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content)>MAX_RESPONSE:status=413;content=bytearray(b'Response exceeds 25MB');break
                    raw=content.decode('utf8',errors='replace')
            except httpx.TransportError:status=0;raw='Network error'
            if 200<=status<300 or status not in RETRY or attempt==attempts-1:break
            delay=delays[attempt];notes.append(f'HTTP {status} 重试 {attempt+1}/{attempts}，等待 {delay*1000}ms');await asyncio.sleep(delay)
        return status,raw
    async def generate(self,args,query):
        prompt=str(args.get('prompt') or '').strip()
        if not prompt:raise ValueError('prompt不能为空')
        cfg=self.config;base=cfg.get('base_url') or cfg.get('url');key=cfg.get('api_key')
        if not base:raise RuntimeError('autobots.autoagent.image_generation.base_url 未配置')
        if not key:raise RuntimeError('autobots.autoagent.image_generation.api_key 未配置')
        model=cfg.get('model') or 'gpt-image-2.5-flare'
        grok=model.lower().startswith('grok-') or 'imagine-image' in model.lower()
        if grok:model=cfg.get('grok_model') or 'grok-imagine-image-lite'
        sources=[str(x).strip() for x in args.get('fileNames') or [] if x and str(x).strip()];masks=[str(x or '').strip() for x in args.get('maskFileNames') or []]
        rawmode=str(args.get('mode') or '').strip();mode=rawmode if rawmode in ('images','edits') else 'edits' if sources else 'images'
        if mode=='edits' and not sources:raise ValueError('图生图模式至少需要一张参考图片')
        if len(masks)>len(sources):raise ValueError('maskFileNames 数量不能超过 fileNames')
        n=max(1,min(10,int(args.get('n') or 1)));size=size_value(args.get('size') or '1024x1024',prompt);level=tier(size)
        notes=['mode='+mode,'size='+size,'model='+model];fallback=False;results=[]
        async def call(path,body,images=None,aggressive=False):return await self.call(base,key,path,body,images,aggressive,notes)
        loaded=[];mask=None
        if mode=='edits':
            for i,ref in enumerate(sources):loaded.append(await self.reference(ref,query,f'fileNames[{i}]'))
            if sum(len(x[1]) for x in loaded)>8*1024*1024:raise ValueError('参考图累计超过 8MB 上限')
            loaded_masks=[] if grok else [await self.reference(ref,query,f'maskFileNames[{i}]') for i,ref in enumerate(masks) if ref]
            mask=loaded_masks[0] if loaded_masks else None
        if grok:
            base=cfg.get('grok_base_url') or base;key=cfg.get('grok_api_key') or key;w,h=map(int,size.split('x'));ratio=min(RATIOS,key=lambda r:abs(w/h-int(r.split(':')[0])/int(r.split(':')[1])))
            body=dict(model=model,prompt=prompt,n=n,resolution='2k' if max(w,h)>=1600 else '1k',aspect_ratio=ratio,response_format='b64_json')
            if loaded:
                if len(loaded)==1:
                    body['reference_image']=data_url(loaded[0][1],loaded[0][2])
                    if masks:notes.append('Grok 路径当前不支持 mask，已忽略 maskFileNames')
                else:body.update(image_urls=[data_url(x[1],x[2]) for x in loaded],prompt='Reference images are provided. Synthesize their visual elements into ONE single new image.\n\nInstruction:\n'+prompt)
            status,raw=await call('/v1/images/generations',body,aggressive=True)
            if not 200<=status<300:raise RuntimeError(f'Grok 生图失败 HTTP {status}')
            results=extract(raw)
        elif mode=='images':
            effective=n
            if level in ('2k','4k') and n>1:notes.append(f'{level.upper()} 强制 N=1，已忽略请求的 n={n}');effective=1
            errors=[]
            for i in range(effective):
                status,raw=await call('/v1/images/generations',dict(model=model,prompt=prompt,n=1,size=size,response_format='b64_json'),aggressive='pro' in model.lower() or level in ('2k','4k'))
                if status in FALLBACK and level in ('2k','4k'):
                    fallback=True;notes.append(f'generations HTTP {status} → fallback chat stream（size 可能不生效）')
                    status,raw=await call('/v1/chat/completions',dict(model=model,messages=[dict(role='user',content=prompt)],stream=False),aggressive='pro' in model.lower())
                found=extract(raw) if 200<=status<300 else []
                if found:results.append(found[0])
                else:errors.append(f'#{i+1} HTTP {status}: 上游未返回可识别图片')
            if not results:raise RuntimeError('; '.join(errors) or '文生图失败')
        else:
            if level=='4k':raise ValueError('size='+size+' (4K) 在图生图已禁用：请改用 2K，或先 1K/2K 再文生图升 4K')
            if len(loaded)>10:raise ValueError('参考图最多 10 张')
            body=dict(model=model,prompt=prompt,size=size,response_format='b64_json');uploads=[('image' if len(loaded)==1 else 'image[]',x) for x in loaded]
            if len(loaded)==1:
                body['n']=n
                if mask:uploads.append(('mask',('mask.png',mask[1],mask[2])))
            status,raw=await call('/v1/images/edits',body,uploads,'pro' in model.lower() or level=='2k')
            if status in FALLBACK:
                fallback=True;notes.append(f"{'edits' if len(loaded)==1 else 'multi-ref edits'} HTTP {status} → fallback chat completions")
                directive='Output the full edited image at exactly '+size+' pixels.'
                header=('Edit the attached image as described. ' if len(loaded)==1 else f'Attached are {len(loaded)} reference images. Use them together to produce one final image. ')+directive+'\n\nInstruction:\n'+prompt
                content=[dict(type='text',text=header)]+[dict(type='image_url',image_url={'url':data_url(x[1],x[2])}) for x in loaded]
                if mask and len(loaded)==1:
                    content.insert(0,dict(type='text',text='The second attached image is an alpha mask: transparent pixels mark the ONLY region to modify.'));content.append(dict(type='image_url',image_url={'url':data_url(mask[1],mask[2])}))
                status,raw=await call('/v1/chat/completions',dict(model=model,messages=[dict(role='user',content=content)],stream=False),aggressive='pro' in model.lower())
            if not 200<=status<300:raise RuntimeError(f'图生图失败 HTTP {status}')
            results=extract(raw)
            if len(loaded)>1:results=results[:1]
        if not results:raise RuntimeError('上游未返回可识别图片')
        if getattr(self.api,'resources',None):await self.api.resources.require(query.visitor_id,'file_scope',query.session_id)
        base_name=re.sub(r'[<>:"/\\|?*\x00-\x1f]+','_',str(args.get('fileName') or '图片生成结果').strip()).rstrip('. ').strip()[:120] or '图片生成结果'
        stem=base_name.rsplit('.',1)[0] if '.' in base_name[1:] else base_name;files=[]
        for i,result in enumerate(results):
            raw,kind=decode(result) if result.startswith('data:') else await self.bytes(result,MAX_RESPONSE)
            kind=mime(raw);ext={'image/jpeg':'jpg','image/webp':'webp','image/gif':'gif'}.get(kind,'png');name=stem+('_'+str(i+1) if len(results)>1 else '')+'.'+ext
            response=await self.api.client.post(self.api.base_url+'/v1/file_tool/upload_file_data',data={'requestId':query.session_id},files={'file':(name,raw,kind)},headers=self.api.headers);response.raise_for_status();value=response.json()
            files.append(dict(fileName=name,downloadUrl=value['downloadUrl'],ossUrl=value['downloadUrl'],previewUrl=value.get('domainUrl') or value['downloadUrl'],domainUrl=value.get('domainUrl') or value['downloadUrl'],fileSize=value.get('fileSize',len(raw)),mimeType=kind))
        summary=('图片编辑' if mode=='edits' else '图片生成')+f"完成，共生成 {len(files)} 个图片文件："+'、'.join(f['fileName'] for f in files)+('；已自动切换兼容接口' if fallback else '')
        return dict(data=summary,fileInfo=files,requestId=query.session_id,mode=mode,usedFallback=fallback,rawResponse=dict(model=model,size=size,notes=notes,imageCount=len(files)),prompt=prompt,size=size,batchCount=n,sourceImageCount=len(sources),maskImageCount=sum(bool(x) for x in masks))
