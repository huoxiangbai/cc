"""Production local tools and run-scoped policy. Remote tools retain their adapter."""
import asyncio
import json
from importlib.resources import files
from pathlib import Path
from reactor_backend.models.types import ToolReply, encode
from reactor_backend.adapters.interactions import decoded
from reactor_backend.runtime.workspace import Workspace

CATALOG=json.loads(files('reactor_backend.tools').joinpath('runtime_schemas.json').read_text())
CATALOG.update(json.loads(files('reactor_backend.tools').joinpath('p4_schemas.json').read_text()))
CATALOG.update(json.loads(files('reactor_backend.tools').joinpath('p5_schemas.json').read_text()))
TASKS={'TaskCreate','TaskGet','TaskUpdate','TaskList','TodoWrite'}
CHILD_DENIED={'Agent','AskUserQuestion','EnterPlanMode','ExitPlanMode','TaskStop','TaskOutput','SendMessage','memory','session_search','fact_store','viking_memory',
              'memory_write','memory_store','memory_forget','write_memory','forget_memory'}
DEFAULT_PLANNER=set('Agent,TaskCreate,TaskGet,TaskUpdate,TaskList,TodoWrite,TaskStop,TaskOutput,SendMessage,EnterPlanMode,ExitPlanMode,AskUserQuestion,ToolSearch,ListMcpResources,ReadMcpResource,workspace_read,workspace_list,workspace_glob,workspace_grep,workspace_write,workspace_edit,skill_tool,memory,session_search,emit_ui_patch,emit_ui_tree,list_ui_components,get_genui_guide,image_ocr,canvas_publish,pdf_reader,pdf_structure,word_reader,text_processor,markdown_processor,html_processor,excel_reader,csv_processor'.split(','))
SEARCH={'deep_search','web_search','WebSearch','web_fetch','WebFetch','session_search','twitter','reddit','xueqiu'}
MUTATING={'code_interpreter','document_generate','slides_generate','excel_generator','checklist_generate','template_filler','canvas_publish','emit_ui_tree','emit_ui_patch','image_generation','image_generation_tool','data_analysis','multimodalagent_tool'}


class YieldInput(Exception):
    def __init__(self, kind, content, path=None):
        self.kind,self.content,self.path=kind,content,path


class ToolScope:
    def __init__(self, runtime, control, query, *, child=None, plan=None, definition=None, disabled=()):
        self.runtime,self.control,self.query=runtime,control,query
        self.child,self.plan,self.definition=child,plan or {},definition
        self.disabled={kind:set(refs) for kind,refs in disabled.items()} if isinstance(disabled,dict) else {'skill':set(disabled),'mcp':set()}
        self.workspace=Workspace(runtime.settings.workspace_root,query.session_id)
        self.skill_scope=None
        if runtime.settings.skill_scope_policy=='session-copy':
            from reactor_backend.skills.registry import SkillScope
            self.skill_scope=SkillScope(runtime.skills,self.workspace,self.disabled['skill'])
        self.schemas=list(runtime.tools.schemas)+list(CATALOG.values())
        self.schemas+=runtime.memory.providers.schemas
        self.mcp=None
        if query.output_style=="dataAgent":self.schemas=[s for s in self.schemas if s["function"]["name"] in ("data_analysis","memory","session_search")]
        if child:
            allowed=set(decoded(definition.get('allowed_tools_json'),[]) or ['*'])
            denied=CHILD_DENIED|set(decoded(definition.get('disallowed_tools_json'),[]))
            self.schemas=[s for s in self.schemas if s['function']['name'] not in denied and ('*' in allowed or s['function']['name'] in allowed)]
        elif query.agent_type==3:
            allowed=set(runtime.settings.planner_tools) or DEFAULT_PLANNER
            self.schemas=[s for s in self.schemas if s['function']['name'] in allowed]
        self.allowed={s['function']['name'] for s in self.schemas}

    async def initialize(self):
        from reactor_backend.mcp.runtime import Catalog
        await asyncio.to_thread(self.runtime.skills.reload)
        skills=await asyncio.to_thread(self.skill_scope.list) if self.skill_scope else self.runtime.skills.list()
        self.schemas=[{**s,'function':{**s['function'],'description':s['function']['description']+'\nAvailable Skills: '+json.dumps(skills,ensure_ascii=False)}} if s['function']['name']=='skill_tool' else s for s in self.schemas]
        rows=await self.runtime.ledger.enabled_mcps() if hasattr(self.runtime.ledger,'enabled_mcps') else []
        allowed=set(decoded(self.definition.get('allowed_tools_json'),[]) or ['*']) if self.child else set() if self.query.output_style=='dataAgent' else None
        denied=CHILD_DENIED|set(decoded(self.definition.get('disallowed_tools_json'),[])) if self.child else set()
        self.mcp=Catalog(rows,self.disabled['mcp'],allowed,denied)
        await self.mcp.initialize()
        self.allowed.update(self.mcp.tools)

    async def close(self):
        if self.mcp:await self.mcp.close()

    @staticmethod
    def is_search(name):
        lower=name.lower()
        return name in SEARCH or 'search' in lower or 'web_fetch' in lower or lower=='fetch'

    def visible(self):
        return [s for s in self.schemas+(self.mcp.schemas() if self.mcp else []) if not (self.plan.get('mode')=='plan' and self.is_search(s['function']['name']))]

    def denied(self,name,a):
        if self.query.output_style=='dataAgent' and name not in self.allowed:return 'Tool is not allowed in dataAgent mode'
        if self.child and (name in CHILD_DENIED or name not in self.allowed):return 'Tool is not allowed in this child scope'
        if not self.child and self.query.agent_type==3 and name not in self.allowed:return 'Tool is not allowed for the PlanSolve coordinator'
        if name=='skill_tool' and a.get('skill_name',a.get('name')) in self.disabled['skill']:return 'Skill disabled for this session'
        if any(name.startswith('mcp__'+ref+'__') for ref in self.disabled['mcp']):return 'MCP disabled for this session'
        if not self.child and self.plan.get('mode')=='plan':
            if self.is_search(name):return 'Plan mode: 禁止外部检索，请退出计划模式并获得用户批准'
            if name in ('workspace_write','workspace_edit'):
                if str(a.get('path','')).replace('\\','/').removeprefix('./')!='.reactor/plan.md':return 'Plan mode: 只能写入 .reactor/plan.md'
            elif name in MUTATING or any(x in name.lower() for x in ('write','edit','delete','exec','run_command')) and name not in TASKS:
                return 'Plan mode: 工具可能修改状态，请先获得用户批准'
        return None

    async def execute(self,name,a,call,tool_id):
        self.control.checkpoint()
        denied=self.denied(name,a)
        if denied:return ToolReply(failed=True,error=denied)
        if name not in CATALOG and name not in ('memory','session_search','fact_store','viking_memory','ToolSearch','ListMcpResources','ReadMcpResource','skill_tool','bash') and not name.startswith('mcp__'):
            return await self.remote(name,a,call)
        try:
            from reactor_backend.delivery import genui_tools
            if name in genui_tools.NAMES:return await genui_tools.execute(self,name,a)
            if name=='image_generation_tool':return await self.runtime.images.tool(self,a)
            if name in ('memory','session_search','fact_store','viking_memory'):return await self.runtime.memory.execute(self,name,a)
            if name in ('ToolSearch','ListMcpResources','ReadMcpResource') or name.startswith('mcp__'):
                if self.mcp is None:raise ValueError('MCP scope is not initialized')
                return await self.mcp.execute(name,a)
            if name=='skill_tool':return ToolReply(data=await asyncio.to_thread(self.skill_scope.manual,a.get('skill_name')) if self.skill_scope else self.runtime.skills.manual(a.get('skill_name'),self.disabled['skill']))
            if name=='bash':
                a={k:v for k,v in a.items() if not k.startswith('_')}
                if self.skill_scope:
                    a={**a,'_skill_library':await asyncio.to_thread(self.skill_scope.bash_library,str(a.get('command') or '')),'_disabled_skills':list(self.skill_scope.disabled_aliases())}
                elif 'skills/' in str(a.get('command') or '').lower():raise PermissionError('Skill script execution requires an explicitly authorized scope policy')
                return await self.remote(name,a,call)
            if name not in CATALOG:return await self.remote(name,a,call)
            if name in TASKS:
                result,snapshot=await self.runtime.ledger.todo(self.query,name,a)
                if name in ('TaskCreate','TaskUpdate','TodoWrite'):
                    await self.emit('session_tasks',call.id+':tasks',{'resultMap':snapshot})
                return ToolReply(data=result)
            if name.startswith('workspace_') and name in CATALOG:
                data=await asyncio.to_thread(self.skill_scope.execute if self.skill_scope else self.workspace.execute,name,a)
                if name in ('workspace_write','workspace_edit') and str(a.get('path','')).removeprefix('./')=='.reactor/plan.md':
                    self.plan['planContent']=await asyncio.to_thread(self.workspace.read,'.reactor/plan.md')
                    self.plan['planFilePath']='.reactor/plan.md'
                produced=[]
                if name in ('workspace_write','workspace_edit') and not str(a.get('path','')).startswith(('skills/','.reactor/')) and hasattr(self.runtime.tools,'client'):
                    produced=[await genui_tools.register(self,a['path'])]
                return ToolReply(data={'tool':name,'ok':True,**data},files=produced)
            if name=='EnterPlanMode':
                if self.plan.get('mode')!='plan':
                    self.plan.update(prePlanMode=self.plan.get('mode','default'),mode='plan',hasExitedPlanMode=False,exitPendingApproval=False)
                await self.emit('plan_mode_entered',call.id,{'resultMap':{'mode':'plan','message':'Entered plan mode'}})
                return ToolReply(data=dict(tool=name,ok=True,mode='plan',message='Plan mode active. Explore read-only, write .reactor/plan.md, then ExitPlanMode.'))
            if name=='ExitPlanMode':
                if self.plan.get('mode')!='plan':raise ValueError('当前不在 plan mode')
                plan=str(a.get('plan') or '').strip()
                if not plan:
                    try:plan=await asyncio.to_thread(self.workspace.read,'.reactor/plan.md')
                    except FileNotFoundError:plan=self.plan.get('planContent')
                if not plan:raise ValueError('计划正文为空')
                await asyncio.to_thread(self.workspace.write,'.reactor/plan.md',plan)
                path=str(self.runtime.settings.workspace_root/self.query.session_id/'.reactor/plan.md')
                self.plan.update(exitPendingApproval=True,pendingPlanContent=plan,planContent=plan,planFilePath=path)
                raise YieldInput('approval',plan,path)
            if name=='AskUserQuestion':
                qs=a.get('questions')
                if not isinstance(qs,list) or not qs:raise ValueError('questions 必须为非空数组')
                # Original normalize truncates to four; schema validation is not strengthened silently.
                normalized=[dict(q) for q in qs if isinstance(q,dict)][:4]
                if not normalized:raise ValueError('questions 不能为空')
                raise YieldInput('question',normalized)
            if name=='Agent':return await self.runtime.subagents.dispatch(self,a,call,tool_id)
            if name in ('TaskOutput','TaskStop','SendMessage'):return await self.runtime.subagents.task_tool(self,name,a)
            return await self.runtime.tools.execute(name,a,self.query)
        except (YieldInput,asyncio.CancelledError):raise
        except Exception as exc:
            return ToolReply(failed=True,error=name+' 失败：'+str(exc))

    async def emit(self,kind,mid,values,**kwargs):
        if self.child:
            tags={k:v for k,v in self.child.items() if k!='agent_name'}
            values={**values,**tags}
            if isinstance(values.get('resultMap'),dict):values['resultMap']={**values['resultMap'],**tags}
        await self.control.emit(kind,mid,values,**kwargs)

    async def remote(self,name,a,call):
        if hasattr(self.runtime.tools,'execute_scoped'):
            async def progress(kind,payload):
                await self.emit(kind,call.id+':progress',{'resultMap':{**payload,'toolCallId':call.id}})
            return await self.runtime.tools.execute_scoped(name,a,self.query,progress)
        return await self.runtime.tools.execute(name,a,self.query)
