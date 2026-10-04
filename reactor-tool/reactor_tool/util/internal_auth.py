"""Opt-in internal service authentication for the protected Python deployment."""
import contextvars
import hmac
import os
from urllib.parse import urlsplit
from starlette.responses import JSONResponse

analysis_scope=contextvars.ContextVar('reactor_analysis_scope',default='')


def scoped_identity():
    import base64,hashlib,json,time
    try:
        payload,sig=analysis_scope.get().rsplit('.',1)
        expected=hmac.new(os.environ['REACTOR_TOOL_SERVICE_TOKEN'].encode(),payload.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig,expected):raise ValueError()
        value=json.loads(base64.urlsafe_b64decode(payload))
        if value['exp']<time.time() or not value['visitor'] or not value['session']:raise ValueError()
        if any(x in value['session'] for x in ('/','\\')) or value['session'] in ('.','..'):raise ValueError()
        return value
    except Exception:raise PermissionError('Verified document scope required') from None


def service_headers():
    token=os.getenv('REACTOR_TOOL_SERVICE_TOKEN','')
    return {'X-Reactor-Service-Token':token} if token else {}


def callback_headers():
    return {**service_headers(),'X-Reactor-Analysis-Scope':analysis_scope.get()}


def file_headers(url):
    # Never send internal credentials to an arbitrary external URL.
    for key in ('FILE_SERVER_INTERNAL_URL','FILE_SERVER_URL'):
        configured=os.getenv(key,'')
        if configured and urlsplit(configured).netloc==urlsplit(url).netloc:
            return callback_headers()
    return {}


class InternalServiceAuth:
    def __init__(self,app):
        self.app=app
        self.required=os.getenv('REACTOR_TOOL_AUTH_REQUIRED','false').lower()=='true'
        self.token=os.getenv('REACTOR_TOOL_SERVICE_TOKEN','')
        if self.required and len(self.token)<32:raise ValueError('Protected Tool requires a service token of at least 32 characters')
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or not self.required:return await self.app(scope,receive,send)
        path=scope['path']
        if not (path.startswith('/v1/') or path.startswith('/_reactor/')):return await self.app(scope,receive,send)
        headers=dict(scope['headers'])
        if not hmac.compare_digest(headers.get(b'x-reactor-service-token',b''),self.token.encode()):
            return await JSONResponse({'detail':'Internal authentication required'},status_code=403)(scope,receive,send)
        context=analysis_scope.set(headers.get(b'x-reactor-analysis-scope',b'').decode())
        try:await self.app(scope,receive,send)
        finally:analysis_scope.reset(context)


def install_internal_auth(app):
    app.add_middleware(InternalServiceAuth)
    # Trusted backend checks legacy existence before any creator reservation.
    from fastapi import Request
    @app.get('/_reactor/security')
    async def security():return {'internal_auth':os.getenv('REACTOR_TOOL_AUTH_REQUIRED','false').lower()=='true'}
    @app.post('/_reactor/resource_exists')
    async def exists(request:Request):
        body=await request.json();kind,key=body.get('kind'),body.get('key')
        if not key or '/' in key or '\\' in key or key in ('.','..'):return JSONResponse({'detail':'Invalid resource'},status_code=400)
        if kind=='file_scope':
            from reactor_tool.db.file_table_op import FileInfoOp
            from pathlib import Path
            root=Path(os.getenv('FILE_SAVE_PATH','file_db_dir')).resolve()
            safe=''.join(c if c not in '<>:"/\\|?*' else '_' for c in key)
            return {'exists':bool(await FileInfoOp.get_by_request_id(key)) or (root/safe).exists()}
        if kind=='kb':
            from reactor_tool.tool.mrag.storage.store_factory import get_kb_store
            store=get_kb_store()
            return {'exists':bool(next((k for k in store.get_kbs(1,100000) if k.kb_id==key),None))}
        return JSONResponse({'detail':'Invalid resource kind'},status_code=400)
