"""Fixed upstream model fixture, ONLY used by P1 tests/browser contract validation."""
import asyncio
import json
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

app=FastAPI()
requests=[]
CONTENT = "# P1 隔离验收\n\n真实工具生成的中文文件。销售额：125。\n"

@app.post("/v1/chat/completions")
async def complete(request: Request):
    body=await request.json()
    requests.append(body)
    messages=body["messages"]
    last_user=max(i for i,m in enumerate(messages) if m["role"] == "user")
    turn=messages[last_user:]
    count=sum(m["role"] == "tool" for m in turn)
    query=messages[last_user]["content"]
    if "MODEL_FAIL" in query:
        return JSONResponse({"error":{"message":"isolated failure"}},status_code=401)
    if "DISCONNECT" in query:
        await asyncio.sleep(.4)
    if "SECOND_TURN" in query:
        assert any(m.get("tool_call_id") == "call-p1-write" for m in messages[:last_user])
        m={"content":"上一轮真实工具交付销售额125；跨轮上下文已读取。"}
    elif "TOOL_FAIL" in query and not count:
        m={"content":"尝试读取缺失文件。","tool_calls":[{"id":"call-fail","type":"function","function":{"name":"text_processor","arguments":json.dumps({"operation":"read","file_path":"missing.txt"})}}]}
    elif "TOOL_FAIL" in query:
        assert turn[-1]["content"].startswith("Error: ")
        m={"content":"text_processor 报告文件不存在，未伪造结果。"}
    elif not count:
        m={"content":"写入报告。","tool_calls":[{"id":"call-p1-write","type":"function","function":{"name":"text_processor","arguments":json.dumps({"operation":"write","file_path":"报告.md","data":CONTENT},ensure_ascii=False)}}]}
    elif count == 1:
        assert json.loads(turn[-1]["content"])["ok"] is True
        m={"content":"读取并核实报告。","tool_calls":[{"id":"call-p1-read","type":"function","function":{"name":"text_processor","arguments":json.dumps({"operation":"read","file_path":"报告.md"},ensure_ascii=False)}}]}
    else:
        assert "125" in turn[-1]["content"]
        m={"content":"已生成并核实报告.md，销售额125。"}
    finish="tool_calls" if m.get("tool_calls") else "stop"
    if not body.get("stream"):
        return {"model":"p1-fixed-upstream","choices":[{"message":m,"finish_reason":finish}],"usage":{"prompt_tokens":20,"completion_tokens":10,"total_tokens":30}}
    async def chunks():
        # Deliberately fragment UTF-8 content and function arguments across provider SSE deltas.
        deltas=[{"content":m.get("content","")[:3]},{"content":m.get("content","")[3:]}]
        for i,call in enumerate(m.get("tool_calls",[])):
            function=call["function"]
            deltas += [{"tool_calls":[{"index":i,"id":call["id"],"function":{"name":function["name"],"arguments":function["arguments"][:8]}}]},
                       {"tool_calls":[{"index":i,"function":{"arguments":function["arguments"][8:]}}]}]
        for delta in deltas:
            yield "data:"+json.dumps({"model":"p1-fixed-upstream","choices":[{"delta":delta,"finish_reason":None}]},ensure_ascii=False)+"\n\n"
        yield "data:"+json.dumps({"choices":[{"delta":{},"finish_reason":finish}],"usage":{"prompt_tokens":20,"completion_tokens":10,"total_tokens":30}})+"\n\n"
        yield "data:[DONE]\n\n"
    return StreamingResponse(chunks(),media_type="text/event-stream")
