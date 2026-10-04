"""Original config tables/DTOs and the approved additive opaque admin sessions."""
import hashlib
import re
import secrets
from sqlalchemy import text
from reactor_backend.adapters.mysql import rows

SPECS = {
 'admin-user': ('admin_user','userId',('userId','username','password','status')),
 'ai-client-api': ('ai_client_api','apiId',('apiId','baseUrl','apiKey','completionsPath','embeddingsPath','status')),
 'ai-client-model': ('ai_client_model','modelId',('modelId','apiId','modelName','modelType','modelUsage','supportsThinking','contextWindow','status')),
 'ai-client-tool-mcp': ('ai_client_tool_mcp','mcpId',('mcpId','mcpName','transportType','transportConfig','requestTimeout','status')),
}

def snake(key):return re.sub(r'(?<!^)(?=[A-Z])','_',key).lower()
def dto(row):
    if row is None:return None
    return {re.sub(r'_([a-z])',lambda m:m[1].upper(),k):v for k,v in row.items() if k!='password'}


class AdminStore:
    def __init__(self,ledger):self.ledger=ledger

    async def check(self):
        await self.ledger.transact(lambda c:rows(c,'SELECT token_digest FROM ai_agent_admin_session LIMIT 0'))

    async def credentials(self,username,password):
        result=await self.ledger.transact(lambda c:rows(c,'SELECT id,user_id,username,status,create_time,update_time FROM admin_user WHERE username=:u AND password=:p AND status=1',u=username,p=password))
        return dto(result[0]) if result else None

    async def login(self,username,password):
        def work(c):
            found=rows(c,'SELECT id,user_id,username,status,create_time,update_time FROM admin_user WHERE username=:u AND password=:p AND status=1 FOR UPDATE',u=username,p=password)
            if not found:return None,None
            token=secrets.token_urlsafe(32)
            c.execute(text('INSERT INTO ai_agent_admin_session(token_digest,admin_user_id,expires_at) VALUES(:d,:a,DATE_ADD(NOW(),INTERVAL 8 HOUR))'),dict(d=hashlib.sha256(token.encode()).hexdigest(),a=found[0]['id']))
            return dto(found[0]),token
        return await self.ledger.transact(work)

    async def authenticate(self,token):
        if not token:return None
        found=await self.ledger.transact(lambda c:rows(c,'SELECT a.id,a.user_id,a.username,a.status,a.create_time,a.update_time FROM ai_agent_admin_session s JOIN admin_user a ON a.id=s.admin_user_id WHERE s.token_digest=:d AND s.revoked_at IS NULL AND s.expires_at>NOW() AND a.status=1',d=hashlib.sha256(token.encode()).hexdigest()))
        return dto(found[0]) if found else None

    async def logout(self,token):
        if token:await self.ledger.transact(lambda c:c.execute(text('UPDATE ai_agent_admin_session SET revoked_at=NOW() WHERE token_digest=:d AND revoked_at IS NULL'),dict(d=hashlib.sha256(token.encode()).hexdigest())))

    async def query(self,kind,operation,value=None,filters=None):
        table,key,fields=SPECS[kind];filters=filters or {}
        def work(c):
            where='';params={}
            field=None
            if operation.startswith('query-by-'):
                field=snake(operation[9:].replace('-','_'))
                allowed={'id',*(snake(f) for f in fields)}-{'password','api_key'}
                if field not in allowed:raise ValueError('Unknown configuration selector')
                where=' WHERE '+field+'=:value';params['value']=value
            elif operation=='query-enabled':where=' WHERE status=1'
            order=' ORDER BY create_time DESC'+(',id DESC' if kind=='ai-client-model' else '')
            if kind=='ai-client-model' and field=='model_id':order=" ORDER BY CASE WHEN LOWER(TRIM(model_usage)) IN ('fallback','backup','备用','备用模型') THEN 1 ELSE 0 END,id DESC"
            columns='id,'+','.join(snake(f) for f in fields)+',create_time,update_time'
            found=rows(c,'SELECT '+columns+' FROM '+table+where+order,**params)
            if operation=='query-list':
                if kind=='ai-client-model':
                    for f in ('modelId','apiId','modelType'):
                        if str(filters.get(f) or '').strip():found=[r for r in found if r[snake(f)]==filters[f]];break
                    else:
                        if filters.get('status')==1:found=[r for r in found if r['status']==1]
                elif kind=='ai-client-tool-mcp':
                    for f in ('mcpId','status','transportType'):
                        if filters.get(f) is not None and filters[f]!='':
                            found=[r for r in found if r[snake(f)]==filters[f]]
                            if f=='mcpId':found=found[:1]
                            break
                    if str(filters.get('mcpName') or '').strip():found=[r for r in found if filters['mcpName'] in (r['mcp_name'] or '')]
                else:
                    for f in fields:
                        val=filters.get(f)
                        if val is None or val=='':continue
                        if f not in ('password','apiKey','completionsPath','embeddingsPath','transportConfig','requestTimeout'):
                            found=[r for r in found if (r.get(snake(f))==val if f in ('status','userId','apiId','transportType') else str(val) in str(r.get(snake(f)) or ''))]
                    page=int(filters.get('pageNum') or 1);size=int(filters.get('pageSize') or 10);start=(page-1)*size
                    if page<1 or size<0 or kind=='admin-user' and start>len(found):raise ValueError('Invalid page bounds')
                    found=found[start:start+size]
            single=field in {'id',snake(key),'username'} and not (kind=='ai-client-model' and field in {'api_id','model_type'})
            return dto(found[0]) if single and found else None if single else [dto(r) for r in found]
        return await self.ledger.transact(work)

    async def mutate(self,kind,operation,data=None,value=None):
        table,key,fields=SPECS[kind];data=data or {}
        by='id' if operation.endswith('by-id') else snake(key)
        selector=value if value is not None else data.get('id' if by=='id' else key)
        if operation!='create' and (selector is None or not str(selector).strip()):raise ValueError('ID不能为空' if by=='id' else {'userId':'用户ID','apiId':'API ID','modelId':'模型ID','mcpId':'MCP ID'}[key]+'不能为空')
        def work(c):
            if kind=='ai-client-model' and by=='model_id' and operation!='create':
                if data.get('id') is not None and operation.startswith('update'):return self._update(c,table,fields,'id',data['id'],data)
                matches=rows(c,'SELECT id FROM ai_client_model WHERE model_id=:v FOR UPDATE',v=selector)
                if len(matches)!=1:raise ValueError('模型ID存在多条配置，请使用记录ID'+('更新' if operation.startswith('update') else '删除'))
            if operation=='create':
                cols=[snake(f) for f in fields];params={snake(f):data.get(f) for f in fields}
                c.execute(text('INSERT INTO '+table+' ('+','.join(cols)+',create_time,update_time) VALUES('+','.join(':'+f for f in cols)+',NOW(),NOW())'),params);return True
            if operation.startswith('delete'):return c.execute(text('DELETE FROM '+table+' WHERE '+by+'=:v'),dict(v=selector)).rowcount>0
            return self._update(c,table,fields,by,selector,data)
        return await self.ledger.transact(work)

    @staticmethod
    def _update(c,table,fields,by,selector,data):
        cols=[snake(f) for f in fields if snake(f)!=by];params={snake(f):data.get(f) for f in fields};params['selector']=selector
        return c.execute(text('UPDATE '+table+' SET '+','.join(f+'=:'+f for f in cols)+',update_time=NOW() WHERE '+by+'=:selector'),params).rowcount>0

    async def subagents(self,key=None):
        def work(c):
            found=rows(c,'SELECT * FROM ai_agent_sub_agent_definition WHERE deleted=0'+(' AND agent_key=:key' if key is not None else '')+' ORDER BY id',key=key)
            import json
            def view(r):return dict(agentKey=r['agent_key'],displayName=r['display_name'],whenToUse=r['when_to_use'],systemPrompt=r['system_prompt'],allowedTools=json.loads(r['allowed_tools_json'] or '[]'),disallowedTools=json.loads(r['disallowed_tools_json'] or '[]'),maxSteps=r['max_steps'],status=r['status'])
            return view(found[0]) if key is not None and found else None if key is not None else [view(r) for r in found]
        return await self.ledger.transact(work)

    async def subagent_write(self,operation,data):
        import json
        key=str(data.get('agentKey') or '').strip()
        if not key:raise ValueError('agentKey 不能为空')
        if key.lower()=='general-purpose':raise ValueError('禁止覆盖内置子 Agent: '+key)
        if operation!='delete':
            if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_/-]{1,62}',key):raise ValueError('agentKey 格式非法：字母开头，仅含字母数字_-/长度2-63')
            if not str(data.get('whenToUse') or '').strip():raise ValueError('whenToUse 不能为空')
            if not str(data.get('systemPrompt') or '').strip():raise ValueError('systemPrompt 不能为空')
            if data.get('maxSteps') is not None and data['maxSteps']<=0:raise ValueError('maxSteps 必须为正整数或留空')
        def tools(value):return json.dumps(list(dict.fromkeys(v.strip() for v in value or [] if v and v.strip()))) if value else None
        def work(c):
            existing=rows(c,'SELECT id FROM ai_agent_sub_agent_definition WHERE agent_key=:key AND deleted=0 FOR UPDATE',key=key)
            if operation=='delete':return c.execute(text('UPDATE ai_agent_sub_agent_definition SET deleted=1,update_time=NOW() WHERE agent_key=:key AND deleted=0'),dict(key=key)).rowcount>0
            if bool(existing)!=(operation=='update'):raise ValueError('agentKey '+('已存在: ' if existing else '不存在: ')+key)
            params=dict(key=key,name=(data.get('displayName') or '').strip() or None,use=data['whenToUse'].strip(),prompt=data['systemPrompt'],allow=tools(data.get('allowedTools')),deny=tools(data.get('disallowedTools')),steps=data.get('maxSteps'),status=0 if data.get('status')==0 else 1)
            if operation=='create':sql='INSERT INTO ai_agent_sub_agent_definition(agent_key,display_name,when_to_use,system_prompt,allowed_tools_json,disallowed_tools_json,max_steps,status) VALUES(:key,:name,:use,:prompt,:allow,:deny,:steps,:status)'
            else:sql='UPDATE ai_agent_sub_agent_definition SET display_name=:name,when_to_use=:use,system_prompt=:prompt,allowed_tools_json=:allow,disallowed_tools_json=:deny,max_steps=:steps,status=:status,update_time=NOW() WHERE agent_key=:key AND deleted=0'
            return c.execute(text(sql),params).rowcount>0
        return await self.ledger.transact(work)
