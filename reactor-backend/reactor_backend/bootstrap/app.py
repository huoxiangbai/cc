from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI
from reactor_backend.bootstrap.config import Settings
from reactor_backend.bootstrap.ownership import single_worker
from reactor_backend.adapters.mysql import MySQLLedger
from reactor_backend.adapters.model import HTTPModel, ModelCatalog
from reactor_backend.adapters.tool_api import ToolAPI
from reactor_backend.runtime.react import ReAct
from reactor_backend.application.runs import Runs
from reactor_backend.transport.http import install


def create_app(settings=None, *, ledger=None, model=None, tools=None):
    settings = settings or Settings.from_env()
    ledger = ledger or MySQLLedger(settings.mysql_url)
    # Explicit adapters only; injected ports are for isolated tests, never an env-selected demo mode.
    client = httpx.AsyncClient(timeout=httpx.Timeout(settings.model_timeout,connect=30),trust_env=False)
    model = model or HTTPModel(client,ModelCatalog(ledger,settings),settings.model_timeout,settings.max_models)
    tools = tools or ToolAPI(client,settings.tool_url,settings.workspace_root,settings.tool_timeout,settings.max_tools,settings=settings,model=model)
    from reactor_backend.adapters.data_catalog import DataCatalog
    from reactor_backend.adapters.business_db import BusinessDB
    from reactor_backend.data_query.service import DataQuery
    from reactor_backend.transport.data import install_data
    resources=None
    if settings.private_tool_gateway:
        from reactor_backend.adapters.private_resources import PrivateResources
        resources=PrivateResources(ledger,tools)
        tools.resources=resources
    data_db=BusinessDB(settings.data_settings.get('db',{}),client)
    data_service=DataQuery(DataCatalog(ledger),data_db,tools,settings.data_settings)
    runs = Runs(ReAct(ledger,model,tools,settings),settings.max_runs)
    from reactor_backend.delivery.images import Images
    runs.runtime.images=Images(ledger,client,tools,settings.image_settings)
    @asynccontextmanager
    async def lifespan(app):
        with single_worker(settings.workspace_root):
            try:
                await ledger.check()
                if isinstance(ledger,MySQLLedger):
                    await app.state.admin_store.check()
                    await app.state.featured.check()
                if hasattr(ledger,"acquire_runtime_owner"):
                    await ledger.acquire_runtime_owner()
                if resources:
                    await resources.check_schema()
                    security=await client.get(settings.tool_url+'/_reactor/security',headers=tools.headers)
                    security.raise_for_status()
                    if security.json().get('internal_auth') is not True:raise ValueError('Tool internal authentication is not enabled')
                await data_service.catalog.initialize(data_db,tools,settings.data_settings)
                if settings.recover_exclusive:
                    from reactor_backend.adapters.recovery import recover
                    app.state.recovery = await recover(ledger)
                yield
            finally:
                await runs.drain()
                await runs.runtime.memory.close()
                import asyncio
                if app.state.data_tasks:await asyncio.gather(*app.state.data_tasks,return_exceptions=True)
                await data_db.close()
                await client.aclose()
                if hasattr(ledger,"release_runtime_owner"):
                    await ledger.release_runtime_owner()
                await ledger.close()
    app = FastAPI(title="Reactor Python backend — P5",lifespan=lifespan)
    app.state.runs, app.state.ledger = runs, ledger
    app.state.private_resources=resources
    app.state.data_tasks=set()
    app.state.data_service=data_service
    if resources:
        from reactor_backend.transport.private_tool import install_private_tool
        install_private_tool(app,resources,settings)
    install_data(app,data_service)
    install(app,ledger,runs,settings)
    from reactor_backend.transport.admin import install_admin
    install_admin(app,ledger,runs,settings,client)
    from reactor_backend.transport.delivery import install_delivery
    install_delivery(app,ledger,runs,settings)
    # CORS must wrap authentication so denied requests retain browser-readable envelopes.
    from starlette.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware,allow_origins=list(settings.cors_origins),
                       allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
    return app
