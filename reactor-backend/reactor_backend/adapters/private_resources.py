"""Persistent creator mappings. Unknown legacy resources cannot be claimed on read."""
import asyncio
import base64
import hashlib
import hmac
import json
import time
from sqlalchemy import text
from reactor_backend.adapters.mysql import rows


class ResourceDenied(ValueError):pass


class PrivateResources:
    def __init__(self,ledger,api):
        self.ledger,self.api=ledger,api
        self.lock=asyncio.Lock()
    async def check_schema(self):
        await self.ledger.transact(lambda c:rows(c,'SELECT resource_key FROM reactor_private_resource_owner LIMIT 0'))
    async def owner(self,kind,key):
        result=await self.ledger.transact(lambda c:rows(c,'SELECT visitor_id FROM reactor_private_resource_owner WHERE resource_kind=:kind AND resource_key=:key',kind=kind,key=key))
        return result[0]['visitor_id'] if result else None
    async def require(self,visitor,kind,key):
        if not visitor or not key or await self.owner(kind,key)!=visitor:raise ResourceDenied('无权访问该资源')
    async def claim_new(self,visitor,kind,key,parent=None):
        if not visitor or not key or len(key)>200:raise ResourceDenied('无效资源身份')
        def work(c):
            c.execute(text('INSERT INTO reactor_private_resource_owner(resource_kind,resource_key,visitor_id,parent_key) VALUES(:kind,:key,:visitor,:parent) ON DUPLICATE KEY UPDATE resource_key=resource_key'),dict(kind=kind,key=key,visitor=visitor,parent=parent))
            found=rows(c,'SELECT visitor_id FROM reactor_private_resource_owner WHERE resource_kind=:kind AND resource_key=:key FOR UPDATE',kind=kind,key=key)
            if found[0]['visitor_id']!=visitor:raise ResourceDenied('无权访问该资源')
        await self.ledger.transact(work)
    async def namespace(self,visitor,key):
        # Only writes to a demonstrably empty new namespace can register a creator.
        if not isinstance(key,str) or not key or '/' in key or '\\' in key or key in ('.','..'):raise ResourceDenied('无效资源范围')
        async with self.lock:
            owner=await self.owner('file_scope',key)
            if owner:return await self.require(visitor,'file_scope',key)
            r=await self.api.client.post(self.api.base_url+'/_reactor/resource_exists',json={'kind':'file_scope','key':key},headers=self.api.headers)
            r.raise_for_status()
            workspace=(self.api.workspace_root/key).resolve()
            if r.json()['exists'] or workspace.exists() and any(workspace.iterdir()):raise ResourceDenied('旧无owner资源需授权映射')
            safe=''.join(c if c not in '<>:"/\\\\|?*' else '_' for c in key)
            await self.claim_new(visitor,'file_physical',safe)
            await self.claim_new(visitor,'file_scope',key)
    async def visible(self,visitor,kind):
        return {r['resource_key'] for r in await self.ledger.transact(lambda c:rows(c,'SELECT resource_key FROM reactor_private_resource_owner WHERE resource_kind=:kind AND visitor_id=:visitor',kind=kind,visitor=visitor))}
    async def existing_identity(self,token):
        if not token:raise ResourceDenied('缺少可信访客身份')
        result=await self.ledger.transact(lambda c:rows(c,"SELECT visitor_id FROM ai_agent_visitor_identity WHERE token_digest=:digest AND status=1 AND deleted=0",digest=hashlib.sha256(token.encode()).hexdigest()))
        if not result:raise ResourceDenied('无效访客身份')
        return result[0]['visitor_id']
    def scope_headers(self,visitor,session):
        payload=base64.urlsafe_b64encode(json.dumps({'visitor':visitor,'session':session,'exp':int(time.time())+1200},separators=(',',':')).encode()).decode()
        token=self.api.settings.tool_service_token
        sig=hmac.new(token.encode(),payload.encode(),hashlib.sha256).hexdigest()
        return {**self.api.headers,'X-Reactor-Analysis-Scope':payload+'.'+sig}
    def verify_scope(self,value):
        try:
            payload,sig=value.rsplit('.',1)
            expected=hmac.new(self.api.settings.tool_service_token.encode(),payload.encode(),hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig,expected):raise ValueError()
            data=json.loads(base64.urlsafe_b64decode(payload))
            if data['exp']<time.time() or not data['visitor'] or not data['session']:raise ValueError()
            return data
        except Exception:raise ResourceDenied('无效内部调用范围') from None
