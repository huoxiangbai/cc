"""Original featured rows, with an explicit publication snapshot of file references."""
import hashlib
import json
from urllib.parse import urlsplit,unquote
from sqlalchemy import text
from reactor_backend.adapters.mysql import rows
from reactor_backend.projection.history import iso,history_view
from reactor_backend.models.types import encode


def resource_path(value):
    path=unquote(urlsplit(value or '').path)
    if path.startswith('/tool/'):path=path[5:]
    if not path.startswith('/v1/file_tool/') or '/..' in path or '\\' in path:return None
    return path

class Featured:
    def __init__(self,ledger):self.ledger=ledger
    async def check(self):await self.ledger.transact(lambda c:rows(c,'SELECT path_digest FROM reactor_featured_resource LIMIT 0'))
    async def published(self,path):
        normalized=resource_path(path)
        if not normalized:return False
        result=await self.ledger.transact(lambda c:rows(c,"SELECT p.id FROM reactor_featured_resource p JOIN ai_agent_featured_conversation f ON f.featured_id=p.featured_id WHERE p.path_digest=:digest AND p.resource_path=:path AND f.status='ONLINE' AND f.deleted=0 LIMIT 1",digest=hashlib.sha256(normalized.encode()).hexdigest(),path=normalized))
        return bool(result)
    def snapshot(self,c,featured,session,cover):
        # Exact artifact references only: private input uploads and arbitrary sibling
        # files do not become public by sharing their directory with a publication.
        artifacts=rows(c,"SELECT a.preview_url,a.download_url FROM ai_agent_artifact a JOIN ai_agent_dialogue_run r ON r.id=a.run_id WHERE r.session_id=:session AND r.deleted=0 AND a.deleted=0 AND a.visibility='visible' AND a.artifact_role='output'",session=session)
        urls=[u for r in artifacts for u in r.values() if u]
        if cover:
            path=resource_path(cover)
            if path and path not in [resource_path(u) for u in urls]:raise ValueError('封面必须引用会话的可发布产物')
            urls.append(cover)
        c.execute(text('DELETE FROM reactor_featured_resource WHERE featured_id=:id'),dict(id=featured))
        for path in set(filter(None,map(resource_path,urls))):
            c.execute(text('INSERT INTO reactor_featured_resource(featured_id,resource_path,path_digest) VALUES(:id,:path,:digest)'),dict(id=featured,path=path,digest=hashlib.sha256(path.encode()).hexdigest()))
    async def mutate(self,operation,data,operator):
        def write(c):
            fid=data.get('featuredId');session=data.get('sessionId')
            if operation in ('online','offline'):
                found=rows(c,'SELECT * FROM ai_agent_featured_conversation WHERE featured_id=:id AND deleted=0 FOR UPDATE',id=fid)
                if not found:return False
                row=found[0]
                if operation=='online':self.snapshot(c,fid,row['session_id'],row['cover_url'])
                else:c.execute(text('DELETE FROM reactor_featured_resource WHERE featured_id=:id'),dict(id=fid))
                return c.execute(text("UPDATE ai_agent_featured_conversation SET status=:status,published_at=IF(:status='ONLINE',NOW(3),published_at),updated_by=:operator,updated_at=NOW(3) WHERE featured_id=:id AND deleted=0"),dict(status=operation.upper(),operator=operator,id=fid)).rowcount>0
            if operation=='create':
                if not session or not session.strip():raise ValueError('sessionId 不能为空')
                session=session.strip()
                if not rows(c,'SELECT id FROM ai_agent_dialogue_session WHERE session_id=:session AND deleted=0',session=session):raise ValueError('sessionId 对应会话不存在')
                fid='featured_'+session
            else:
                if not fid or not str(fid).strip():raise ValueError('featuredId 不能为空')
                if not rows(c,'SELECT id FROM ai_agent_featured_conversation WHERE featured_id=:id AND deleted=0',id=fid):raise ValueError('featuredId 不存在')
                if not session or not str(session).strip():return False
            value=dict(featured_id=fid,session_id=session,title=data.get('title'),summary=data.get('summary'),cover_resource_key=data.get('coverResourceKey'),cover_url=data.get('coverUrl'),tags_json=encode(data.get('tags') or []),sort_order=data.get('sortOrder') or 0,published_by=operator,updated_by=operator)
            columns=','.join(value);args=','.join(':'+k for k in value)
            updated=('title','summary','cover_resource_key','cover_url','tags_json','sort_order','updated_by')
            result=c.execute(text(f'INSERT INTO ai_agent_featured_conversation ({columns},updated_at) VALUES ({args},NOW(3)) ON DUPLICATE KEY UPDATE '+','.join(f'{k}=VALUES({k})' for k in updated)+',updated_at=NOW(3),deleted=0'),value).rowcount>0
            actual=rows(c,'SELECT * FROM ai_agent_featured_conversation WHERE featured_id=:id OR session_id=:session LIMIT 1',id=fid,session=session)[0]
            if actual['status']=='ONLINE':self.snapshot(c,actual['featured_id'],actual['session_id'],actual['cover_url'])
            return result
        return await self.ledger.transact(write)
    @staticmethod
    def view(row,admin=False):
        view=dict(featuredId=row['featured_id'],sessionId=row['session_id'],title=row['title'],summary=row['summary'],coverUrl=row['cover_url'],tags=json.loads(row['tags_json'] or '[]'),publishedAt=iso(row['published_at']))
        if admin:view.update(status=row['status'],sortOrder=row['sort_order'],updatedAt=iso(row['updated_at']))
        else:view['contentLastActiveAt']=iso(row.get('last_active_at'))
        return view
    async def listing(self,page=1,size=20,filters=None,admin=False):
        filters=filters or {};conditions=['f.deleted=0'];params={}
        if not admin:conditions.append("f.status='ONLINE'")
        else:
            for field,wire in [('status','status'),('session_id','sessionId'),('title','title')]:
                if filters.get(wire):conditions.append('f.'+field+(' LIKE :'+field if field=='title' else '=:'+field));params[field]='%'+filters[wire]+'%' if field=='title' else filters[wire]
        def read(c):
            where=' AND '.join(conditions);total=rows(c,'SELECT COUNT(*) n FROM ai_agent_featured_conversation f WHERE '+where,**params)[0]['n']
            found=rows(c,'SELECT f.*,s.last_active_at FROM ai_agent_featured_conversation f LEFT JOIN ai_agent_dialogue_session s ON s.session_id=f.session_id AND s.deleted=0 WHERE '+where+' ORDER BY f.sort_order DESC,f.id DESC LIMIT :offset,:size',**params,offset=(max(1,page)-1)*max(1,size),size=max(1,size))
            return dict(total=total,list=[self.view(r,admin) for r in found])
        return await self.ledger.transact(read)
    async def detail(self,fid):
        found=await self.ledger.transact(lambda c:rows(c,"SELECT f.*,s.last_active_at,s.visitor_id FROM ai_agent_featured_conversation f LEFT JOIN ai_agent_dialogue_session s ON s.session_id=f.session_id AND s.deleted=0 WHERE f.featured_id=:id AND f.status='ONLINE' AND f.deleted=0 LIMIT 1",id=fid))
        if not found:return None
        row=found[0];history=None
        if row.get('visitor_id'):
            session,facts=await self.ledger.history(row['visitor_id'],row['session_id']);history=history_view(session,facts)
            # Publication revocation while the asynchronous history read was in flight
            # must also revoke its response, not just later resource requests.
            current=await self.ledger.transact(lambda c:rows(c,"SELECT id FROM ai_agent_featured_conversation WHERE featured_id=:id AND status='ONLINE' AND deleted=0",id=fid))
            if not current:return None
        return {**self.view(row), 'status':row['status'],'contentAvailable':history is not None,'contentUnavailableReason':None if history is not None else 'session_history_missing','historyDetail':history}
