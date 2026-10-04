from reactor_backend.projection.events import Projector
from reactor_backend.delivery.artifacts import artifact_ref
import json

STATUS = {0:"RUNNING",1:"SUCCESS",2:"FAILED",3:"TIMEOUT",4:"STOPPED",5:"WAITING_INPUT"}


def label(value):
    return STATUS.get(value, "RUNNING")


def iso(value):
    return value.isoformat(timespec="milliseconds").removesuffix(".000") if value else None


def session_view(s):
    return dict(sessionId=s["session_id"],title=s["title"],status=label(s["status"]),
                latestQueryText=s.get("latest_query_text"),runCount=s["run_count"],
                finishedRunCount=s["finished_run_count"],failedRunCount=s["failed_run_count"],
                startedAt=iso(s.get("started_at")),lastActiveAt=iso(s.get("last_active_at")))


def replay(facts):
    run, llms, tools, artifacts = (facts[k] for k in ("run","llms","tools","artifacts"))
    p = Projector(run["request_id"], history=True)
    frames, projected = [], set()
    def tool_event(t):
        from reactor_backend.projection.genui import decode
        from reactor_backend.projection.tool_history import project
        linked_artifacts = [a for a in artifacts if a["tool_invocation_id"] == t["id"]]
        params = decode(t["input_json"], {})
        if not isinstance(params,dict): params = {}
        nesting = {}
        for column,key in (("parent_tool_call_id","parentToolUseId"),("sub_agent_id","subAgentId"),("sub_agent_type","subAgentType"),("sub_agent_description","subAgentDescription")):
            if t.get(column): nesting[key]=t[column]
        if "subAgentType" not in nesting and (t.get("agent_name") or "").startswith("subagent:"):
            nesting["subAgentType"] = t["agent_name"][9:]
        binding = {"toolName":t["tool_name"],"toolParam":params,"toolResult":t.get("llm_oberserve") or t.get("error_msg"),"toolCallId":t["tool_call_id"]}
        structured = project(t,params,linked_artifacts)
        projections = [("tool_result",binding,linked_artifacts)] if structured is None else structured
        for kind,payload,event_artifacts in projections:
            values = dict(nesting)
            if kind == "tool_result":
                values["toolResult"] = payload
                if nesting.get("parentToolUseId"):
                    values["resultMap"] = {**nesting,"toolCallId":t["tool_call_id"],"toolName":t["tool_name"]}
            else:
                values["resultMap"] = {**payload,**nesting,"toolCallId":t["tool_call_id"],"toolName":t["tool_name"]}
            base = t.get("tool_call_id") or t.get("tool_name") or "history-tool"
            refs=[artifact_ref(a) for a in event_artifacts]
            frames.append(p.event(kind,base+":"+kind,values,refs=refs,at=t.get("finished_at") or t.get("started_at")))
        projected.add(t["id"])
    for llm in llms:
        linked = [t for t in tools if t["llm_invocation_id"] == llm["id"]]
        name = llm["agent_name"]
        # Match Java's hidden internal calls and avoid unbound subagent text leaking into main timeline.
        internal = llm.get("call_kind") in ("internalDigitalEmployee", "internalCompact")
        parent = next((t.get("parent_tool_call_id") for t in linked if t.get("parent_tool_call_id")), None)
        hidden = internal or name.startswith("subagent:") and not parent
        if not hidden:
            base = f'{name}:{llm["invocation_seq"]}'
            if llm.get("reasoning_content"):
                frames.append(p.event("llm_reasoning",base+":reasoning",dict(reasoningContent=llm["reasoning_content"]),at=llm.get("finished_at")))
            content = llm.get("response_text")
            if content and (llm["tool_call_count"] or name in ("planning","summary","executor") or not tools):
                kind = "plan_thought" if name == "planning" else "result" if name == "summary" else "task_summary" if name == "executor" and not llm["tool_call_count"] else "tool_thought"
                key = {"plan_thought":"planThought","result":"result","task_summary":"taskSummary","tool_thought":"toolThought"}[kind]
                frames.append(p.event(kind,base,{key:content},at=llm.get("finished_at")))
        for t in linked:
            tool_event(t)
    for t in tools:
        if t["id"] not in projected:
            tool_event(t)
    if run.get("final_summary_text") and not any(f["resultMap"]["eventData"]["resultMap"]["messageType"] == "result" for f in frames):
        frames.append(p.event("result",run["request_id"]+":summary",
                             {"result":run["final_summary_text"],"taskSummary":run["final_summary_text"],"finish":run["status"] != 0},
                             at=run.get("finished_at") or run["started_at"]))
    return frames


def history_view(session, facts, context_window=100000):
    header = session_view(session)
    header.pop("latestQueryText")
    details = []
    for f in facts:
        r = f["run"]
        context = None
        for llm in reversed(f["llms"]):
            prompt = max(0,llm.get("prompt_tokens") or 0)
            total_est = sum(max(0,llm.get(key) or 0) for key in ("est_system_tokens","est_tool_tokens","est_message_tokens"))
            estimated = max(0,llm.get("est_total_tokens") or 0) or total_est
            if prompt or estimated:
                context = dict(sys=llm.get("est_system_tokens") or 0, tools=llm.get("est_tool_tokens") or 0,
                               history=llm.get("est_message_tokens") or 0,files=0,max=f.get("context_windows",{}).get(llm.get("model_name"),context_window),
                               used=prompt or estimated,estimatedTotal=estimated,
                               promptTokens=prompt or None,completionTokens=llm.get("completion_tokens") or None,
                               source="measured" if prompt else "estimate")
                break
        details.append(dict(requestId=r["request_id"], status=label(r["status"]), queryText=r["query_text"],
                            finalSummaryText=r.get("final_summary_text"),startedAt=iso(r["started_at"]),
                            finishedAt=iso(r.get("finished_at")), contextUsage=context, replayFrames=replay(f)))
    header.update(deepThink=bool(facts and facts[-1]["run"]["entry_agent"] == "plan_solve"), runs=details)
    if facts:
        header["status"] = label(facts[-1]["run"]["status"])
    return header
