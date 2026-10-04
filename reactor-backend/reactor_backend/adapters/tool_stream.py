"""Strict SSE decoder for the Tool protocol, independent of Agent SSE."""
import json


async def events(response):
    response.raise_for_status()
    data=[]
    async for line in response.aiter_lines():
        if line.startswith(':'):
            continue
        if line.startswith('data:'):
            data.append(line[5:].lstrip(' '))
        elif not line and data:
            raw='\n'.join(data);data=[]
            if raw=='[DONE]':
                yield None
                return
            if raw.strip() in ('','heartbeat'):
                continue
            event=json.loads(raw)
            if not isinstance(event,dict):
                raise ValueError('Tool SSE must contain JSON objects')
            yield event
    if data:
        raise ValueError('Tool SSE ended inside an event')
