"""Isolation-only host of ORIGINAL Tool/file routers; no substituted tool results.

This fixture does not boot the unrelated OCR/vector/sandbox dependencies. Production
uses the unchanged reactor-tool server.py api/sandbox roles.
"""
from pathlib import Path
import os
import sys
import dotenv
import dotenv.main

# python-dotenv 1.1 starts discovery at its caller source file, not necessarily cwd.
# Restrict configuration discovery before importing the ORIGINAL routers. This changes
# test configuration loading only; original Tool operations/results remain untouched.
if not (Path.cwd()/'ISOLATED_P1').is_file():
    raise RuntimeError('Tool test host requires a freshly provisioned P1 isolation root')
def no_dotenv_discovery(*args, **kwargs):
    return ""
dotenv.find_dotenv = dotenv.main.find_dotenv = no_dotenv_discovery

def forbid_env_reads(event,args):
    if event == 'open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
        if Path(os.fsdecode(args[0])).name == '.env':
            raise RuntimeError('Isolation forbids reading .env')
sys.addaudithook(forbid_env_reads)

from contextlib import asynccontextmanager
from fastapi import FastAPI
from reactor_tool.api.tool import router as tool_router
from reactor_tool.api.file_manage import router as file_router
from reactor_tool.db.db_engine import init_db, async_engine

@asynccontextmanager
async def lifespan(app):
    init_db()
    yield
    await async_engine.dispose()

app = FastAPI(lifespan=lifespan)
from reactor_tool.util.internal_auth import install_internal_auth
install_internal_auth(app)
from starlette.middleware.cors import CORSMiddleware
# Match original server.py so unchanged MRAG/SOP browser clients can reach Tool.
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'],allow_credentials=True)
app.include_router(tool_router,prefix="/v1/tool")
app.include_router(file_router,prefix="/v1/file_tool")

# P3 keeps the original routers and actual code executor. Only model/config are isolated.
if os.environ.get('REACTOR_TEST_PHASE')=='p3':
    from reactor_tool.api.social import router as social_router
    from reactor_tool.api.sandbox_routes import router as sandbox_router
    from reactor_tool.api.sop import router as sop_router
    from reactor_tool.tool.mrag.api.routes.document import router as documents_router
    from reactor_tool.tool.mrag.api.routes.history import router as history_router
    app.include_router(social_router,prefix='/v1/tool')
    app.include_router(sandbox_router,prefix='/v1/tool')
    app.include_router(sop_router,prefix='/v1')
    app.include_router(documents_router,prefix='/v1')
    app.include_router(history_router,prefix='/v1')
