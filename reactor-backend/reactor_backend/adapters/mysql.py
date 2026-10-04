"""Existing MySQL tables; SQL only, no startup DDL, no SQLite fallback."""
import asyncio
from datetime import datetime
import hashlib
import json
from uuid import uuid4
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from reactor_backend.models.types import encode
from reactor_backend.models.scope import agent_scope
from reactor_backend.adapters.tasks import TaskStore
from reactor_backend.adapters.memory_store import MemoryStore

TABLES = {"visitor_identity", "dialogue_session", "dialogue_run", "llm_invocation", "tool_invocation", "artifact", "working_memory_turn", "working_memory_message", "working_memory_compaction", "ltm_curated_entry", "ltm_fork_execution"}


def now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)


def rows(c, sql, **params):
    return [dict(row) for row in c.execute(text(sql), params).mappings()]


def insert(c, table, values):
    assert table in TABLES
    columns = ",".join(values)
    args = ",".join(":" + k for k in values)
    return c.execute(text(f"INSERT INTO ai_agent_{table} ({columns}) VALUES ({args})"), values).lastrowid


def update(c, table, id, values):
    assert table in TABLES
    assignments = ",".join(k + "=:" + k for k in values)
    c.execute(text(f"UPDATE ai_agent_{table} SET {assignments} WHERE id=:row_id AND deleted=0"), {**values, "row_id": id})


class MySQLLedger(TaskStore,MemoryStore):
    def __init__(self, url: str):
        if make_url(url).drivername != "mysql+pymysql":
            raise ValueError("REACTOR_MYSQL_URL must explicitly use mysql+pymysql")
        self.engine = create_engine(url, pool_size=8, max_overflow=0, pool_pre_ping=True,
                                    hide_parameters=True, connect_args={"connect_timeout": 10, "read_timeout": 30, "write_timeout": 30})
        self.gate = asyncio.Semaphore(8)

    async def transact(self, fn):
        async with self.gate:
            def work():
                with self.engine.begin() as c:
                    c.execute(text("SET time_zone = '+08:00'"))
                    return fn(c)
            # Shield ensures cancellation cannot release a pool permit while a DB thread still writes.
            task = asyncio.create_task(asyncio.to_thread(work))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise

    async def check(self):
        await self.transact(lambda c: rows(c, "SELECT id FROM ai_agent_dialogue_run LIMIT 0"))

    async def close(self):
        await asyncio.to_thread(self.engine.dispose)

    async def identity(self, token, ip, ua):
        def work(c):
            existing = rows(c, "SELECT * FROM ai_agent_visitor_identity WHERE token_digest=:digest AND deleted=0 LIMIT 1",
                            digest=hashlib.sha256((token or "").encode()).hexdigest()) if token else []
            if existing and existing[0]["status"] == 1:
                v = existing[0]
                update(c, "visitor_identity", v["id"], {"last_seen_at": now(), "last_ip": ip, "last_user_agent": ua})
                return v, None
            raw = uuid4().hex + uuid4().hex
            v = dict(visitor_id="visitor_" + uuid4().hex, token_digest=hashlib.sha256(raw.encode()).hexdigest(), status=1,
                     first_seen_at=now(), last_seen_at=now(), last_ip=ip, last_user_agent=ua, username=None)
            v["id"] = insert(c, "visitor_identity", v)
            return v, raw
        return await self.transact(work)

    async def name_visitor(self, visitor_id, username):
        username = (username or "").strip()
        if not username:
            raise ValueError("用户名不能为空")
        if len(username.encode("utf-16-le")) // 2 > 32:
            raise ValueError("用户名长度不能超过32个字符")
        def work(c):
            count = c.execute(text("UPDATE ai_agent_visitor_identity SET username=:name WHERE visitor_id=:visitor AND deleted=0 AND (username IS NULL OR TRIM(username)='')"),
                              {"name": username, "visitor": visitor_id}).rowcount
            if count != 1:
                raise ValueError("当前访客已命名，不可修改")
            return rows(c, "SELECT * FROM ai_agent_visitor_identity WHERE visitor_id=:visitor AND deleted=0", visitor=visitor_id)[0]
        return await self.transact(work)

    @staticmethod
    def _owner(c, visitor, session, query=None, create=False):
        if not visitor or not session or not session.strip():
            raise ValueError("visitorId 和 sessionId 不能为空")
        if create:
            # New sessions acquire an owner; legacy unowned rows require an authorized mapping.
            c.execute(text("""INSERT INTO ai_agent_dialogue_session(session_id,visitor_id,title,started_at,last_active_at)
                VALUES(:session,:visitor,:title,:at,:at) ON DUPLICATE KEY UPDATE
                session_id=session_id"""),
                {"session": session, "visitor": visitor, "title": (query or "").strip()[:30] or "新对话", "at": now()})
        result = rows(c, "SELECT * FROM ai_agent_dialogue_session WHERE session_id=:session AND deleted=0 FOR UPDATE", session=session)
        if not result:
            raise ValueError("当前会话不存在")
        s = result[0]
        if not s["visitor_id"] or s["visitor_id"] != visitor:
            raise ValueError("无权访问该资源")
        return s

    async def owner(self, visitor, session, query=None, create=False):
        return await self.transact(lambda c: self._owner(c, visitor, session, query, create))

    async def has_open_interaction(self, session):
        def work(c):
            for table in ("user_question", "plan_approval"):
                c.execute(text(f"UPDATE ai_agent_{table} SET status='TIMEOUT' WHERE session_id=:session AND status='PENDING' AND expires_at<=NOW(3) AND deleted=0"),dict(session=session))
                if rows(c, f"SELECT id FROM ai_agent_{table} WHERE session_id=:session AND deleted=0 AND status IN ('PENDING','RESUME_PENDING','RESUMING') LIMIT 1", session=session):
                    return True
            return False
        return await self.transact(work)

    async def start_run(self, q):
        def work(c):
            s = self._owner(c, q.visitor_id, q.session_id, q.query, True)
            r = dict(run_uid=q.request_id, request_id=q.request_id, session_id=q.session_id, visitor_id=q.visitor_id,
                     entry_agent="plan_solve" if q.agent_type == 3 else "react", status=0, query_text=q.query, started_at=now())
            r["id"] = insert(c, "dialogue_run", r)
            update(c, "dialogue_session", s["id"], {"run_count": s["run_count"] + 1, "status": 0,
                   "latest_request_id": q.request_id, "latest_query_text": q.query, "last_active_at": r["started_at"]})
            return r
        return await self.transact(work)

    async def start_llm(self, run_id, seq, step, model, messages, tools):
        scope = agent_scope.get() or {}
        return await self.transact(lambda c: insert(c, "llm_invocation", dict(run_id=run_id, invocation_seq=seq,
            agent_name=scope.get("agent_name", "react"), step_no=step, call_kind="askTool", streaming=1, model_name=model,
            message_count=len(messages), tool_count=len(tools), started_at=now())))

    async def finish_llm(self, id, reply, error=None):
        def work(c):
            vals = dict(status=2 if error else 1, error_msg=error, finished_at=now())
            if reply:
                vals.update(response_text=reply.content, reasoning_content=reply.reasoning or None,
                    tool_call_count=len(reply.calls), model_name=reply.model, finish_reason=reply.finish_reason,
                    system_fingerprint=reply.fingerprint,
                    prompt_tokens=reply.usage.get("prompt_tokens", 0), completion_tokens=reply.usage.get("completion_tokens", 0),
                    total_tokens=reply.usage.get("total_tokens", 0))
                for source, fields in (("prompt_tokens_details", {"cached_tokens":"cached_prompt_tokens","text_tokens":"prompt_text_tokens","audio_tokens":"prompt_audio_tokens","image_tokens":"prompt_image_tokens"}),
                                       ("completion_tokens_details", {"text_tokens":"completion_text_tokens","audio_tokens":"completion_audio_tokens","reasoning_tokens":"reasoning_tokens"})):
                    for key, column in fields.items():
                        if key in (reply.usage.get(source) or {}):
                            vals[column] = reply.usage[source][key]
            columns=",".join(k+"=:"+k for k in vals)
            c.execute(text("UPDATE ai_agent_llm_invocation SET "+columns+" WHERE id=:id AND status=0 AND deleted=0"),{**vals,"id":id})
            c.execute(text("UPDATE ai_agent_llm_invocation SET duration_ms=TIMESTAMPDIFF(MICROSECOND,started_at,finished_at) DIV 1000 WHERE id=:id"), {"id": id})
        await self.transact(work)

    async def start_tool(self, run_id, llm_id, call, index, step, arguments):
        scope = agent_scope.get() or {}
        return await self.transact(lambda c: insert(c, "tool_invocation", dict(run_id=run_id, llm_invocation_id=llm_id,
            tool_call_id=call.id, dispatch_index=index, agent_name=scope.get("agent_name", "react"), step_no=step,
            parent_tool_call_id=scope.get("parentToolUseId"), sub_agent_id=scope.get("subAgentId"),
            sub_agent_type=scope.get("subAgentType"), sub_agent_description=scope.get("subAgentDescription"),
            tool_name=call.name, tool_provider="local", input_json=encode(arguments), started_at=now())))

    async def finish_tool(self, id, reply, observation):
        def work(c):
            settled = c.execute(text("UPDATE ai_agent_tool_invocation SET status=:status,error_msg=:error,llm_oberserve=:observation,finished_at=:at WHERE id=:id AND status=0 AND deleted=0"),dict(status=3 if reply.timed_out else 2 if reply.failed else 1,error=reply.error,observation=observation,at=now(),id=id))  # Original column spelling is contractual.
            if settled.rowcount:
                from reactor_backend.adapters.tool_outputs import save
                save(c,id,reply,3 if reply.timed_out else 2 if reply.failed else 1)
            c.execute(text("UPDATE ai_agent_tool_invocation SET duration_ms=TIMESTAMPDIFF(MICROSECOND,started_at,finished_at) DIV 1000 WHERE id=:id"), {"id": id})
        await self.transact(work)

    async def register_artifacts(self, run, tool_id, call, files):
        from reactor_backend.delivery.artifacts import artifact_values, artifact_ref
        def work(c):
            result = []
            for f in files:
                value = artifact_values(run, tool_id, call, f)
                cols = ",".join(value)
                args = ",".join(":"+k for k in value)
                c.execute(text(f"INSERT INTO ai_agent_artifact({cols}) VALUES({args}) ON DUPLICATE KEY UPDATE metadata_json=VALUES(metadata_json),download_url=VALUES(download_url),preview_url=VALUES(preview_url)"), value)
                result.append(artifact_ref(value))
            return result
        return await self.transact(work)

    async def finish_run(self, run, status, summary, error, messages, *, projection=None, compactions=()):
        def work(c):
            settled = rows(c,"SELECT status FROM ai_agent_dialogue_run WHERE id=:id AND deleted=0 FOR UPDATE",id=run["id"])
            if not settled or settled[0]["status"] != 0:
                return settled[0]["status"] if settled else None
            if status in (2,3,4):
                for table in ("tool_invocation","llm_invocation"):
                    c.execute(text(f"UPDATE ai_agent_{table} SET status=:status,error_msg=:error,finished_at=NOW(3) WHERE run_id=:run AND status=0 AND deleted=0"),dict(status=status,error=error,run=run["id"]))
            stats = rows(c, "SELECT COUNT(*) AS n,COALESCE(SUM(prompt_tokens),0) AS p,COALESCE(SUM(completion_tokens),0) AS o,COALESCE(SUM(total_tokens),0) AS t FROM ai_agent_llm_invocation WHERE run_id=:id AND deleted=0", id=run["id"])[0]
            counts = {table: rows(c, f"SELECT COUNT(*) AS n FROM ai_agent_{table} WHERE run_id=:id AND deleted=0", id=run["id"])[0]["n"] for table in ("tool_invocation", "artifact")}
            update(c, "dialogue_run", run["id"], dict(status=status, final_summary_text=summary,
                   error_msg=error, error_code="EXECUTION_FAILED" if error else None, finished_at=now(),
                   llm_call_count=stats["n"], tool_call_count=counts["tool_invocation"], artifact_count=counts["artifact"],
                   prompt_tokens_total=stats["p"], completion_tokens_total=stats["o"], total_tokens_total=stats["t"]))
            c.execute(text("UPDATE ai_agent_dialogue_run SET duration_ms=TIMESTAMPDIFF(MICROSECOND,started_at,finished_at) DIV 1000 WHERE id=:id"), {"id": run["id"]})
            s = rows(c, "SELECT * FROM ai_agent_dialogue_session WHERE session_id=:session AND deleted=0 FOR UPDATE", session=run["session_id"])[0]
            update(c, "dialogue_session", s["id"], dict(status=status, latest_summary_text=summary, last_active_at=now(),
                   finished_run_count=s["finished_run_count"] + (status == 1), failed_run_count=s["failed_run_count"] + (status in (2,3,4))))
            self._save_context(c, run, messages)
            compact_id=self.replace_projection(c,run,projection) if projection else None
            for event in compactions:
                insert(c,'working_memory_compaction',dict(session_id=run['session_id'],trigger_request_id=run['request_id'][:64],compact_request_id=compact_id,status=2 if event['strategy']=='abort-unchanged' else 1,**event))
            return status
        return await self.transact(work)

    @staticmethod
    def _save_context(c, run, messages, scope="main"):
        if not messages:
            return
        seq = rows(c, "SELECT COALESCE(MAX(turn_seq),0)+1 AS seq FROM ai_agent_working_memory_turn WHERE session_id=:session AND memory_scope=:scope AND deleted=0", session=run["session_id"],scope=scope)[0]["seq"]
        turn_id = insert(c, "working_memory_turn", dict(session_id=run["session_id"], request_id=run["request_id"], run_id=run["id"],
                       turn_seq=seq, entry_agent=run.get("entry_agent", "react"), memory_scope=scope, status=1, message_count=len(messages), started_at=run["started_at"], finished_at=now()))
        for index, m in enumerate(messages):
            insert(c, "working_memory_message", dict(session_id=run["session_id"], memory_scope=scope, turn_id=turn_id,
                   request_id=run["request_id"], origin_message_key=m.get('_origin') or f'{run["request_id"]}:{index}', run_id=run["id"], seq_no=index,
                   role=m["role"].upper(), content=m.get("content"), reasoning_content=m.get("reasoning_content"), base64_image=m.get("_base64_image"), tool_call_id=m.get("tool_call_id"),
                   tool_calls_json=encode(m["tool_calls"]) if m.get("tool_calls") else None,
                   message_kind="tool_observation" if m["role"] == "tool" else "query" if m["role"] == "user" else "assistant"))

    async def enabled_model_metadata(self):
        columns=("id", "model_id", "api_id", "model_name", "model_type", "model_usage",
                 "supports_thinking", "context_window", "status", "create_time", "update_time")
        records=await self.transact(lambda c:rows(c,"SELECT "+",".join(columns)+" FROM ai_client_model WHERE status=1 ORDER BY create_time DESC,id DESC"))
        def camel(key):
            first,*tail=key.split('_')
            return first+''.join(part.title() for part in tail)
        return [{camel(k):r[k] for k in columns} for r in records]

    async def save_child_context(self, run, messages, scope, *, projection=None, compactions=()):
        def work(c):
            self._save_context(c,run,messages,scope)
            compact_id=self.replace_projection(c,run,projection,scope) if projection else None
            for event in compactions:insert(c,'working_memory_compaction',dict(session_id=run['session_id'],trigger_request_id=run['request_id'][:64],compact_request_id=compact_id,status=2 if event['strategy']=='abort-unchanged' else 1,**event))
        await self.transact(work)

    async def context(self, session_id, scope="main"):
        def work(c):
            data = rows(c, """SELECT m.* FROM ai_agent_working_memory_message m JOIN ai_agent_working_memory_turn t ON t.id=m.turn_id
                WHERE m.session_id=:session AND m.memory_scope IN (:scope,:alias) AND m.deleted=0 AND t.deleted=0 AND t.status=1
                ORDER BY t.started_at,t.id,m.seq_no""", session=session_id,scope=scope,alias=("subagent:"+scope[4:] if scope.startswith("sub:") else "sub:"+scope[9:] if scope.startswith("subagent:") else scope))
            messages = []; seen=set()
            for r in data:
                if r["origin_message_key"] in seen:continue
                seen.add(r["origin_message_key"])
                m = {"role": r["role"].lower(), "content": r["content"]}
                if r.get("reasoning_content"):m["reasoning_content"]=r["reasoning_content"]
                if r.get("base64_image"):m["_base64_image"]=r["base64_image"]
                if r["tool_call_id"]:
                    m["tool_call_id"] = r["tool_call_id"]
                if r["tool_calls_json"]:
                    from reactor_backend.memory.working import normalize_call
                    m["tool_calls"] = [normalize_call(call) for call in (json.loads(r["tool_calls_json"]) if isinstance(r["tool_calls_json"], str) else r["tool_calls_json"])]
                messages.append(m)
            return messages
        return await self.transact(work)

    async def find_run(self, request_id):
        return await self.transact(lambda c: rows(c, "SELECT * FROM ai_agent_dialogue_run WHERE request_id=:req AND deleted=0 LIMIT 1", req=request_id))

    async def recent(self, visitor, limit):
        return await self.transact(lambda c: rows(c, "SELECT * FROM ai_agent_dialogue_session WHERE visitor_id=:visitor AND deleted=0 ORDER BY last_active_at DESC,id DESC LIMIT :limit",
                                                visitor=visitor, limit=20 if limit <= 0 else min(limit, 100)))

    async def history(self, visitor, session):
        def work(c):
            s = self._owner(c, visitor, session)
            runs = rows(c, "SELECT * FROM ai_agent_dialogue_run WHERE session_id=:session AND deleted=0 ORDER BY create_time,id", session=session)
            facts = []
            for r in runs:
                facts.append(dict(run=r, llms=rows(c, "SELECT * FROM ai_agent_llm_invocation WHERE run_id=:id AND deleted=0 ORDER BY invocation_seq,id", id=r["id"]),
                                  tools=rows(c, "SELECT * FROM ai_agent_tool_invocation WHERE run_id=:id AND deleted=0 ORDER BY dispatch_index,started_at,id", id=r["id"]),
                                  artifacts=rows(c, "SELECT * FROM ai_agent_artifact WHERE run_id=:id AND deleted=0 ORDER BY id", id=r["id"])))
            catalog = rows(c,"SELECT model_name,context_window FROM ai_client_model WHERE status=1 ORDER BY create_time DESC,id DESC")
            windows = {}
            for model in catalog:
                if model.get("context_window") and model["context_window"] > 0:
                    windows.setdefault(model["model_name"],model["context_window"])
            for f in facts:
                f["context_windows"] = windows
                for tool in f["tools"]:
                    from reactor_backend.models.tool_outputs import OUTPUT_TABLES
                    if tool["tool_name"] in OUTPUT_TABLES:
                        table = "ai_agent_tool_output_" + OUTPUT_TABLES[tool["tool_name"]]
                        outputs = rows(c, f"SELECT * FROM {table} WHERE tool_invocation_id=:id LIMIT 1", id=tool["id"])
                        tool["structured_output"] = outputs[0] if outputs else None
                    if tool["tool_name"].lower() == "askuserquestion":
                        try: observation = json.loads(tool.get("llm_oberserve") or "{}")
                        except ValueError: observation = {}
                        if not isinstance(observation,dict): observation={}
                        question = rows(c,"SELECT * FROM ai_agent_user_question WHERE deleted=0 AND (question_id=:question OR (session_id=:session AND status IN ('PENDING','RESUME_PENDING','RESUMING') AND (tool_invocation_id=:tool OR tool_call_id=:call))) ORDER BY question_id=:question DESC,id LIMIT 1",question=observation.get("questionId"),session=session,tool=tool["id"],call=tool["tool_call_id"])
                        tool["persisted_question"] = question[0] if question else None
            return s, facts
        return await self.transact(work)

    async def prior_plan_turn(self, session, request):
        return bool(await self.transact(lambda c:rows(c,"SELECT id FROM ai_agent_dialogue_run WHERE session_id=:s AND entry_agent='plan_solve' AND request_id<>:r AND deleted=0 LIMIT 1",s=session,r=request)))

    async def waiting_tool(self, id, observation):
        await self.transact(lambda c:c.execute(text("UPDATE ai_agent_tool_invocation SET status=5,llm_oberserve=:o,finished_at=NOW(3) WHERE id=:id AND status=0 AND deleted=0"),{'o':observation,'id':id}))

    async def apply_continuation(self, record, observation):
        def work(c):
            self.authorize(c,record['visitor_id'],record['session_id'])
            c.execute(text("UPDATE ai_agent_working_memory_message SET content=:o WHERE session_id=:s AND request_id=:r AND memory_scope='main' AND tool_call_id=:call AND role='TOOL' AND deleted=0"),dict(o=observation,s=record['session_id'],r=record['source_request_id'],call=record['tool_call_id']))
            c.execute(text('UPDATE ai_agent_tool_invocation SET llm_oberserve=:o WHERE id=:id AND status=5 AND deleted=0'),dict(o=observation,id=record['tool_invocation_id']))
        await self.transact(work)

    async def settle_agent_tool(self, id, observation):
        # Receipt→settled only, never a late receipt over an already settled observation.
        await self.transact(lambda c:c.execute(text("UPDATE ai_agent_tool_invocation SET llm_oberserve=:o WHERE id=:id AND deleted=0 AND tool_name='Agent' AND JSON_VALID(llm_oberserve) AND JSON_UNQUOTE(JSON_EXTRACT(llm_oberserve,'$.status'))='running'"),dict(o=observation,id=id)))

    async def refresh_run_counts(self, run_id):
        await self.transact(lambda c:c.execute(text('''UPDATE ai_agent_dialogue_run r SET
            llm_call_count=(SELECT COUNT(*) FROM ai_agent_llm_invocation l WHERE l.run_id=r.id AND l.deleted=0),
            tool_call_count=(SELECT COUNT(*) FROM ai_agent_tool_invocation t WHERE t.run_id=r.id AND t.deleted=0),
            artifact_count=(SELECT COUNT(*) FROM ai_agent_artifact a WHERE a.run_id=r.id AND a.deleted=0),
            prompt_tokens_total=(SELECT COALESCE(SUM(prompt_tokens),0) FROM ai_agent_llm_invocation l WHERE l.run_id=r.id AND l.deleted=0),
            completion_tokens_total=(SELECT COALESCE(SUM(completion_tokens),0) FROM ai_agent_llm_invocation l WHERE l.run_id=r.id AND l.deleted=0),
            total_tokens_total=(SELECT COALESCE(SUM(total_tokens),0) FROM ai_agent_llm_invocation l WHERE l.run_id=r.id AND l.deleted=0)
            WHERE r.id=:id AND r.deleted=0'''),dict(id=run_id)))

    async def acquire_runtime_owner(self):
        # Named lock covers Python processes with different workspace roots but the same DB.
        # This does not prove an old Java owner exited; recovery additionally requires an explicit exclusive declaration.
        def acquire():
            c=self.engine.connect()
            database=c.execute(text('SELECT DATABASE()')).scalar()
            name='reactor-python-owner:'+str(database)
            if c.execute(text('SELECT GET_LOCK(:name,0)'),dict(name=name)).scalar()!=1:
                c.close()
                raise RuntimeError('Another Python runtime owns this database')
            self.runtime_owner=c
            self.runtime_owner_name=name
        await asyncio.to_thread(acquire)

    async def release_runtime_owner(self):
        c=getattr(self,'runtime_owner',None)
        if c:
            def release():
                try:c.execute(text('SELECT RELEASE_LOCK(:name)'),dict(name=self.runtime_owner_name))
                finally:c.close()
            await asyncio.to_thread(release)
            self.runtime_owner=None
