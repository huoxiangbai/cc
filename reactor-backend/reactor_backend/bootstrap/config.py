"""Explicit configuration; never discovers or loads the Java/Tool .env."""
from dataclasses import dataclass,field
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    mysql_url: str = field(repr=False)
    tool_url: str
    workspace_root: Path
    model_base_url: str | None = None
    model_api_key: str | None = field(default=None,repr=False)
    model_name: str | None = None
    system_prompt: str = ""
    cookie_secure: bool = True
    cookie_name: str = "ai_agent_visitor_token"
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")
    max_steps: int = 150
    tool_timeout: float = 210
    model_timeout: float = 1200
    max_runs: int = 32
    max_tools: int = 128
    max_models: int = 64
    heartbeat_seconds: float = 10
    context_window: int = 100000
    planner_model: str | None = None
    planner_max_steps: int = 400
    planner_tools: tuple[str, ...] = ()
    model_protocol: str = "function_call"
    fallback_models: tuple[str, ...] = ()
    max_subagents: int = 4
    subagent_wait_seconds: float = 30
    recover_exclusive: bool = False
    skill_root: Path | None = None
    skill_scope_policy: str | None = 'session-copy'
    llm_settings: dict = field(default_factory=dict,repr=False)
    memory_settings: dict = field(default_factory=dict,repr=False)
    compaction_settings: dict = field(default_factory=dict,repr=False)

    research_timeout: float = 600
    deepsearch_engines: tuple[str,...] = ()
    mrag_kb_ids: tuple[str,...] = ()
    analysis_models: tuple[str,...] = ()
    tool_service_token: str | None = field(default=None,repr=False)
    private_tool_gateway: bool = False
    web_search: dict = field(default_factory=dict,repr=False)
    image_settings: dict = field(default_factory=dict,repr=False)
    data_settings: dict = field(default_factory=dict,repr=False)

    @classmethod
    def from_env(cls):
        import json
        if os.environ.get("WEB_CONCURRENCY", "1") != "1" or os.environ.get("REACTOR_BACKEND_WORKERS", "1") != "1":
            raise ValueError("Reactor requires a single backend worker")
        required = ("REACTOR_MYSQL_URL", "REACTOR_TOOL_URL", "REACTOR_WORKSPACE_ROOT")
        missing = [key for key in required if not os.environ.get(key)]
        if missing:
            raise ValueError("Missing explicit configuration: " + ", ".join(missing))
        return cls(mysql_url=os.environ["REACTOR_MYSQL_URL"],
                   tool_url=os.environ["REACTOR_TOOL_URL"].rstrip("/"),
                   workspace_root=Path(os.environ["REACTOR_WORKSPACE_ROOT"]).resolve(),
                   system_prompt=Path(os.environ["REACTOR_SYSTEM_PROMPT_FILE"]).read_text() if os.environ.get("REACTOR_SYSTEM_PROMPT_FILE") else Path(__file__).parents[1].joinpath("runtime/system_prompt.txt").read_text(),
                   model_base_url=os.environ.get("REACTOR_MODEL_BASE_URL"),
                   model_api_key=os.environ.get("REACTOR_MODEL_API_KEY"),
                   model_name=os.environ.get("REACTOR_MODEL_NAME"),
                   research_timeout=float(os.environ.get("REACTOR_RESEARCH_TIMEOUT","600")),
                   deepsearch_engines=tuple(filter(None,os.environ.get("REACTOR_DEEPSEARCH_ENGINES", "").split(","))),
                   mrag_kb_ids=tuple(filter(None,os.environ.get("REACTOR_MRAG_KB_IDS", "").split(","))),
                   analysis_models=tuple(filter(None,os.environ.get("REACTOR_ANALYSIS_MODELS", "").split(","))),
                   tool_service_token=os.environ.get("REACTOR_TOOL_SERVICE_TOKEN"),
                   private_tool_gateway=True,
                   web_search=json.loads(Path(os.environ["REACTOR_WEB_SEARCH_CONFIG_FILE"]).read_text()) if os.environ.get("REACTOR_WEB_SEARCH_CONFIG_FILE") else {},
                   data_settings=json.loads(Path(os.environ["REACTOR_DATA_CONFIG_FILE"]).read_text()) if os.environ.get("REACTOR_DATA_CONFIG_FILE") else {},
                   image_settings=json.loads(Path(os.environ['REACTOR_IMAGE_CONFIG_FILE']).read_text()) if os.environ.get('REACTOR_IMAGE_CONFIG_FILE') else {},
                   cookie_secure=os.environ.get("REACTOR_COOKIE_SECURE", "true").lower() == "true",
                   planner_model=os.environ.get("REACTOR_PLANNER_MODEL"),
                   planner_max_steps=int(os.environ.get("REACTOR_PLANNER_MAX_STEPS", "400")),
                   planner_tools=tuple(filter(None,os.environ.get("REACTOR_PLANNER_TOOLS", "").split(","))),
                   max_steps=int(os.environ.get("REACTOR_MAX_STEPS", "150")),
                   max_subagents=int(os.environ.get("REACTOR_MAX_SUBAGENTS", "4")),
                   subagent_wait_seconds=float(os.environ.get("REACTOR_SUBAGENT_WAIT_SECONDS", "30")),
                   model_protocol=os.environ.get("REACTOR_MODEL_PROTOCOL", "function_call"),
                   fallback_models=tuple(filter(None,os.environ.get("REACTOR_FALLBACK_MODELS", "").split(","))),
                   recover_exclusive=os.environ.get("REACTOR_RECOVER_EXCLUSIVE", "false").lower() == "true",
                   skill_root=Path(os.environ["REACTOR_SKILL_ROOT"]).resolve() if os.environ.get("REACTOR_SKILL_ROOT") else None,
                   skill_scope_policy=os.environ.get('REACTOR_SKILL_SCOPE_POLICY','session-copy'),
                   llm_settings=json.loads(Path(os.environ['REACTOR_LLM_SETTINGS_FILE']).read_text()) if os.environ.get('REACTOR_LLM_SETTINGS_FILE') else {},
                   memory_settings=json.loads(Path(os.environ['REACTOR_MEMORY_CONFIG_FILE']).read_text()) if os.environ.get('REACTOR_MEMORY_CONFIG_FILE') else {},
                   compaction_settings=json.loads(Path(os.environ['REACTOR_COMPACTION_CONFIG_FILE']).read_text()) if os.environ.get('REACTOR_COMPACTION_CONFIG_FILE') else {})

    def __post_init__(self):
        if self.skill_scope_policy not in (None,'session-copy'):raise ValueError('Unknown Skill scope policy')
        if min(self.max_steps,self.planner_max_steps,self.max_subagents,self.subagent_wait_seconds)<=0:
            raise ValueError('Step and subagent limits must be positive')
        if self.private_tool_gateway and (not self.tool_service_token or len(self.tool_service_token)<32):
            raise ValueError('Protected backend requires an explicit service token of at least 32 characters')
        if self.model_protocol not in ('function_call','struct_parse'):
            raise ValueError('Invalid model tool protocol')
        if not isinstance(self.llm_settings,dict) or any(not isinstance(v,dict) for v in self.llm_settings.values()):
            raise ValueError('LLM settings must map model references to parameter objects')
