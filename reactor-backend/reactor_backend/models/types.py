"""Protocol-independent values and required runtime ports."""
from dataclasses import dataclass, field
from typing import Any, Protocol
import json


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class Query:
    request_id: str
    session_id: str
    visitor_id: str
    query: str | None
    trace_id: str
    user: str
    agent_type: int
    model: str | None = None
    thinking: bool | None = None
    thinking_effort: str | None = None
    force_plan_mode: bool = False
    session_files: list | None = None
    output_style: str | None = None
    resume: dict | None = field(default=None, compare=False)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str

    def wire(self) -> dict:
        return {"id": self.id, "type": "function", "function": {
            "name": self.name, "arguments": self.arguments}}


@dataclass
class ModelReply:
    content: str = ""
    reasoning: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    finish_reason: str | None = None
    model: str | None = None
    fingerprint: str | None = None

    def message(self) -> dict:
        message = {"role": "assistant", "content": self.content or None}
        if self.reasoning:message["reasoning_content"]=self.reasoning
        if self.calls:
            message["tool_calls"] = [call.wire() for call in self.calls]
        return message


@dataclass
class ToolReply:
    data: Any = None
    failed: bool = False
    error: str | None = None
    files: list[dict] = field(default_factory=list)
    structured_output: Any = None
    timed_out: bool = False
    wire_observation: str | None = None

    def observation(self) -> str:
        if self.wire_observation is not None:text=self.wire_observation
        elif self.failed:
            text = encode({"tool_ok": False, "error": self.error, "detail": self.data}) if self.data else "Error: " + (self.error or "Unknown error")
        else:
            text = self.data if isinstance(self.data, str) else encode(self.data)
        if len(text) > 96000:
            text = text[:96000] + "\n...[output truncated for context cap; narrow the query or use a smaller path]..."
        return text


class ModelPort(Protocol):
    async def complete(self, messages: list[dict], tools: list[dict], query: Query) -> ModelReply: ...


class ToolPort(Protocol):
    schemas: list[dict]
    async def execute(self, name: str, arguments: dict, query: Query) -> ToolReply: ...


class LedgerPort(Protocol):
    async def start_run(self, query: Query) -> dict: ...
    async def start_llm(self, run_id: int, seq: int, step: int, model: str | None, messages: list, tools: list) -> int: ...
    async def finish_llm(self, id: int, reply: ModelReply | None, error: str | None = None) -> None: ...
    async def start_tool(self, run_id: int, llm_id: int, call: ToolCall, index: int, step: int, arguments: Any) -> int: ...
    async def finish_tool(self, id: int, reply: ToolReply, observation: str) -> None: ...
    async def register_artifacts(self, run: dict, tool_id: int, call: ToolCall, files: list) -> list: ...
    async def finish_run(self, run: dict, status: int, summary: str, error: str | None, messages: list) -> None: ...
    async def context(self, session_id: str) -> list[dict]: ...
