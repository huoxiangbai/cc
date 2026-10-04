from reactor_backend.models.types import Query


def trim(value):
    return str(value).strip() or None if value is not None else None


def normalize(body: dict, visitor_id: str) -> Query:
    user = body.get("user") if body.get("user") is not None else "reactor"
    deep = body.get("deepThink") if body.get("deepThink") is not None else 0
    session = body.get("sessionId")
    request = body.get("requestId")
    trace = trim(body.get("traceId")) or f'{user}{session if session is not None else "null"}:{request if request is not None else "null"}'
    return Query(request_id=trim(request) or trace, session_id=session,
                 visitor_id=visitor_id, query=body.get("query"), trace_id=trace,
                 user=user, agent_type=3 if deep != 0 else 5,
                 model=trim(body.get("model")), thinking=body.get("thinking"),
                 thinking_effort=trim(body.get("thinkingEffort")),
                 force_plan_mode=body.get("forcePlanMode") is True,
                 session_files=body.get("sessionFiles"),
                 output_style="dataAgent" if body.get("outputStyle") == "dataAgent" else None)
