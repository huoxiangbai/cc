"""Tokens are created at admission, before execution binding; no browser ownership."""
import asyncio
from collections import deque
from reactor_backend.projection.events import Projector


class RunControl:
    def __init__(self, query, publish):
        self.query=query
        self.publish=publish
        self.cancelled=False
        self.root_closed=False
        self.root_task=None
        self.children=set()
        self.injections=deque()
        self.mailboxes={}
        self.projector=Projector(query.request_id)
        self.projector.agent_type=query.agent_type
        self.llm_seq=0
        self.run=None

    def checkpoint(self):
        if self.cancelled:
            raise asyncio.CancelledError('Run stopped')

    def stop(self):
        first=not self.cancelled
        self.cancelled=True
        # Before root binding the token is sufficient; binding checks it before external work.
        if self.root_task and not self.root_closed:
            self.root_task.cancel()
        for task in tuple(self.children):
            task.cancel()
        return first

    async def emit(self, kind, mid, values, **kwargs):
        # No awaits between projection and enqueue: all scopes share one event sequence owner.
        error=kwargs.pop("errorMsg",None)
        event=self.projector.event(kind,mid,values,**kwargs)
        if error:event["errorMsg"]=error
        await self.publish(event)

    async def drain(self):
        while self.children:
            await asyncio.gather(*tuple(self.children),return_exceptions=True)

    def next_llm(self):
        self.llm_seq+=1
        return self.llm_seq
