"""Real OpenAI-compatible HTTP adapter; aggregation never fabricates final text."""
import asyncio
import json
import re
from uuid import uuid4
from reactor_backend.models.scope import model_scope
from reactor_backend.models.types import encode
from dataclasses import dataclass,field,replace
from reactor_backend.models.types import ModelReply, ToolCall
from reactor_backend.adapters.mysql import rows

TRANSIENT = {408,409,425,429,500,502,503,504,520,521,522,523,524,525,527}
FALLBACK = {"fallback", "backup", "备用", "备用模型"}


@dataclass(frozen=True)
class ModelBinding:
    model: str
    base_url: str
    api_key: str = field(repr=False)
    path: str = "/v1/chat/completions"
    supports_thinking: bool = False
    context_window: int = 100000
    max_tokens: int = 16384
    temperature: float = 0.0
    protocol: str = "function_call"
    reasoning_effort: str | None = None
    extra_body: dict = field(default_factory=dict,repr=False)


class ModelFailure(RuntimeError):
    def __init__(self, message, transient=False, fallback=True):
        super().__init__(message)
        self.transient = transient
        self.fallback = fallback


class ModelCatalog:
    def __init__(self, ledger, settings):
        self.ledger, self.settings = ledger, settings

    def parameters(self,binding,ref,db_window=None):
        config=self.settings.llm_settings.get((ref or '').strip(),self.settings.llm_settings.get(binding.model,{}))
        extras=dict(config.get('extParams') or {})
        aliases={'maxTokens':'max_tokens','maxCompletionTokens':'max_completion_tokens','topP':'top_p',
                 'frequencyPenalty':'frequency_penalty','presencePenalty':'presence_penalty','reasoningEffort':'reasoning_effort'}
        extras={aliases.get(k,k):v for k,v in extras.items()}
        if any(k in extras for k in ('model','messages','tools','stream','stream_options','tool_choice')):
            raise ModelFailure('Sampling extras cannot replace request identity or tool protocol',fallback=False)
        max_tokens=int(extras.pop('max_tokens',config.get('max_tokens',binding.max_tokens)))
        temperature=float(extras.pop('temperature',config.get('temperature',binding.temperature)))
        window=db_window if db_window and db_window>0 else config.get('max_input_tokens') or binding.context_window
        if max_tokens<=0 or int(window)<=0:raise ModelFailure('Invalid model token budget',fallback=False)
        return replace(binding,max_tokens=max_tokens,temperature=temperature,context_window=int(window),
                       protocol=config.get('functionCallType') or binding.protocol,
                       reasoning_effort=config.get('reasoning_effort'),extra_body=extras)

    async def bindings(self):
        bindings = await self.ledger.transact(lambda c: rows(c, """SELECT m.*,a.base_url,a.api_key,a.completions_path
            FROM ai_client_model m JOIN ai_client_api a ON a.api_id=TRIM(m.api_id)
            WHERE m.status=1 AND a.status=1 AND TRIM(m.model_id)<>'' AND TRIM(m.model_name)<>'' AND TRIM(a.base_url)<>'' AND TRIM(a.api_key)<>'' ORDER BY m.create_time DESC,m.id DESC"""))
        for b in bindings:
            for key in ("model_id","model_name","base_url","api_key"):
                b[key] = b[key].strip()
            b["completions_path"] = (b.get("completions_path") or "").strip() or None
        return bindings

    async def chain(self, ref):
        bindings = await self.bindings()
        primary = await self.resolve(ref, bindings)
        chain = [primary]
        for row in bindings:
            if (row.get("model_usage") or "").strip().lower() in FALLBACK:
                candidate = await self.resolve("__db_binding__:" + str(row["id"]), bindings)
                if candidate not in chain:
                    chain.append(candidate)
        for name in self.settings.fallback_models:
            candidate = await self.resolve(name, bindings)
            if candidate not in chain:
                chain.append(candidate)
        return chain

    async def resolve(self, ref, bindings=None):
        bindings = await self.bindings() if bindings is None else bindings
        ref = (ref or "").strip() or None
        chosen = None
        if bindings:
            if not ref or ref.lower() == "default":
                chosen = next((b for b in bindings if (b.get("model_usage") or "").strip().lower() not in FALLBACK), bindings[0])
            elif ref.startswith("__db_binding__:"):
                chosen = next((b for b in bindings if str(b["id"]) == ref[len("__db_binding__:"): ]), None)
            else:
                for key in ("model_id", "model_name"):
                    matches = [b for b in bindings if b[key] == ref]
                    if matches:
                        chosen = next((b for b in matches if (b.get("model_usage") or "").strip().lower() not in FALLBACK), matches[0])
                        break
            if chosen:
                binding=ModelBinding(chosen["model_name"], chosen["base_url"], chosen["api_key"],
                    chosen["completions_path"] or "/chat/completions", bool(chosen["supports_thinking"]),
                    chosen["context_window"] or self.settings.context_window, protocol=self.settings.model_protocol)
                return self.parameters(binding,ref,chosen['context_window'])
            raise ModelFailure("Requested model is not configured or enabled")
        s = self.settings
        if not s.model_name or not s.model_base_url:
            raise ModelFailure("No enabled model binding or explicit REACTOR_MODEL_NAME/BASE_URL")
        if ref and ref not in ("default", s.model_name):
            raise ModelFailure("Requested model is not configured")
        base = s.model_base_url.rstrip("/")
        path = "/chat/completions" if base.endswith("/v1") else "/v1/chat/completions"
        return self.parameters(ModelBinding(s.model_name, base, s.model_api_key or "", path, protocol=s.model_protocol),ref)


class HTTPModel:
    def __init__(self, client, catalog, timeout=1200, concurrency=64, retry_delay=.5):
        self.client, self.catalog, self.timeout = client, catalog, timeout
        self.gate = asyncio.Semaphore(concurrency)
        self.retry_delay = retry_delay

    async def complete(self, messages, tools, query):
        chain = await self.catalog.chain(query.model) if hasattr(self.catalog, "chain") else [await self.catalog.resolve(query.model)]
        scope = model_scope.get()
        for index, binding in enumerate(chain):
            record = await scope.begin(binding.model) if scope else None
            try:
                reply = await self._binding(messages, tools, query, binding, scope)
            except asyncio.CancelledError:
                if scope:
                    await scope.end(record, None, "Cancelled")
                raise
            except Exception as exc:
                if scope:
                    await scope.end(record, None, str(exc))
                if index + 1 == len(chain) or not isinstance(exc, ModelFailure) or not exc.fallback:
                    raise
                if scope:
                    await scope.notify("llm_fallback", {"fromModel": binding.model, "toModel": chain[index+1].model, "reason": str(exc)})
            else:
                if scope:
                    await scope.end(record, reply, None)
                return reply

    async def _binding(self, messages, tools, query, binding, scope):
        if binding.protocol not in ("function_call", "struct_parse"):
            raise ModelFailure("Invalid model tool protocol", fallback=False)
        from reactor_backend.memory.working import model_messages
        prompt = model_messages(messages)
        if binding.protocol == "struct_parse" and tools:
            prompt = [{"role":"system", "content":
                'Use fenced ```json blocks for tool calls, each object contains function_name and argument fields. Available tools: ' + encode(tools)}] + prompt
            # Text gateways cannot consume native tool roles; preserve the full observation and identity in text.
            prompt = [{"role":"user" if m["role"] == "tool" else m["role"], "content":
                ("Tool result " + m.get("tool_call_id", "") + ": " + (m.get("content") or "")) if m["role"] == "tool" else
                (m.get("content") or "") + ("\nTool calls: " + encode(m["tool_calls"]) if m.get("tool_calls") else "")} for m in prompt]
        body = {"model": binding.model, "messages": prompt, "stream": True,
                "stream_options": {"include_usage": True}, "max_tokens":binding.max_tokens,"temperature":binding.temperature}
        if binding.reasoning_effort:body['reasoning_effort']=binding.reasoning_effort
        body.update(binding.extra_body)
        if tools and binding.protocol == "function_call":
            body.update(tools=tools, tool_choice="auto")
        if query.thinking is not None and binding.supports_thinking:
            body["enable_thinking"] = query.thinking
            if query.thinking and query.thinking_effort:
                body["reasoning_effort"] = query.thinking_effort
        url = binding.base_url.rstrip("/") + "/" + binding.path.lstrip("/")
        headers = {"Authorization": "Bearer " + binding.api_key, "Content-Type": "application/json"}
        rescued = False
        async with self.gate:
            for attempt in range(6):
                try:
                    async with asyncio.timeout(self.timeout):
                        reply = await self._stream(url, headers, body)
                        if not reply.content.strip() and not reply.calls and not rescued:
                            rescued = True
                            rescue_body = {k:v for k,v in body.items() if k != "stream_options"}
                            response = await self.client.post(url, headers=headers, json={**rescue_body, "stream": False})
                            self._status(response)
                            reply = self._json(response.json())
                        if binding.protocol == "struct_parse":
                            reply = self._struct(reply)
                        if not reply.content.strip() and not reply.calls:
                            raise ModelFailure("Empty model response", True)
                        reply.model = reply.model or binding.model
                        return reply
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    import httpx
                    transient = isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, json.JSONDecodeError, TimeoutError)) or isinstance(exc, ModelFailure) and exc.transient
                    if "CERTIFICATE_VERIFY_FAILED" in str(exc) or "hostname mismatch" in str(exc):
                        transient = False
                    if not transient or attempt == 5:
                        if isinstance(exc, ModelFailure):
                            raise
                        raise ModelFailure("Model transport failed: " + type(exc).__name__, transient) from exc
                    if scope:
                        await scope.notify("llm_retry", {"model": binding.model, "attempt": attempt+1, "maxRetries":5})
                    await asyncio.sleep(min(4, self.retry_delay * 2 ** attempt))

    @staticmethod
    def _struct(reply):
        calls = []
        for block in re.findall(r"```json\s*([\s\S]*?)\s*```", reply.content):
            try:
                obj = json.loads(block)
                name = obj.pop("function_name")
                if not isinstance(name, str) or not name.strip():
                    continue
                calls.append(ToolCall(uuid4().hex, name, encode(obj)))
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
        reply.content = reply.content.split("```json", 1)[0].strip()
        reply.calls = calls
        return reply

    @staticmethod
    def _status(response):
        if response.status_code >= 400:
            # Never persist raw upstream bodies/keys or HTTP client request representations.
            raise ModelFailure(f"Model HTTP {response.status_code}", response.status_code in TRANSIENT,
                               response.status_code not in (400,413,414,422))

    async def _stream(self, url, headers, body):
        reply = ModelReply()
        calls = {}
        async with self.client.stream("POST", url, headers=headers, json=body) as response:
            self._status(response)
            if "text/event-stream" not in response.headers.get("content-type", ""):
                await response.aread()
                return self._json(response.json())
            done = False
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw == "[DONE]":
                    done = True
                    break
                if not raw:
                    continue
                chunk = json.loads(raw)
                if chunk.get("error"):
                    raise ModelFailure("Model returned a streaming error", True)
                reply.model = chunk.get("model") or reply.model
                reply.fingerprint = chunk.get("system_fingerprint") or reply.fingerprint
                reply.usage = chunk.get("usage") or reply.usage
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta") or {}
                    reply.content += delta.get("content") or ""
                    reply.reasoning += delta.get("reasoning_content") or delta.get("reasoning") or ""
                    reply.finish_reason = choice.get("finish_reason") or reply.finish_reason
                    for call in delta.get("tool_calls") or []:
                        target = calls.setdefault(call["index"], {"id": "", "name": "", "arguments": ""})
                        target["id"] += call.get("id") or ""
                        target["name"] += (call.get("function") or {}).get("name") or ""
                        target["arguments"] += (call.get("function") or {}).get("arguments") or ""
            if not done and not reply.finish_reason:
                raise ModelFailure("Truncated model stream", True)
        reply.calls = [ToolCall(**calls[index]) for index in sorted(calls)]
        if any(not c.id or not c.name for c in reply.calls):
            raise ModelFailure("Incomplete tool-call identity")
        return reply

    @staticmethod
    def _json(data):
        if data.get("error"):
            raise ModelFailure("Model returned an error")
        choices = data.get("choices") or []
        if not choices:
            return ModelReply(usage=data.get("usage") or {})
        m = choices[0].get("message") or {}
        return ModelReply(content=m.get("content") or "", reasoning=m.get("reasoning_content") or "",
                          calls=[ToolCall(c["id"],c["function"]["name"],c["function"]["arguments"]) for c in m.get("tool_calls") or []],
                          usage=data.get("usage") or {}, model=data.get("model"),
                          finish_reason=choices[0].get("finish_reason"), fingerprint=data.get("system_fingerprint"))
