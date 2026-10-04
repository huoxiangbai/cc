"""Supervisor owns business tasks; a replaced/disconnected observer owns no execution."""
import asyncio
from collections import deque
from reactor_backend.projection.events import frame
from reactor_backend.runtime.control import RunControl


class RunStream:
    def __init__(self,query):
        self.query=query
        self.buffer=deque(maxlen=128)
        self.observers=set()
        self.closed=False
        self.task=None
        self.control=RunControl(query,self.publish)

    async def publish(self,event):
        if self.closed:return
        if event.get('packageType')!='heartbeat':self.buffer.append(event)
        for q in tuple(self.observers):
            if q.full():
                self.detach(q,close=True)
            else:q.put_nowait(event)

    def detach(self,q,close=False):
        # Identity of an old queue cannot detach its replacement.
        self.observers.discard(q)
        if close:
            while not q.empty():q.get_nowait()
            q.put_nowait(None)

    def close(self):
        self.closed=True
        for q in tuple(self.observers):
            if q.full():q.get_nowait()
            q.put_nowait(None)
        self.observers.clear()

    def attach(self,cursor=0):
        # Java rebind replaces a single observer under the same sequence boundary.
        for old in tuple(self.observers):self.detach(old,close=True)
        q=asyncio.Queue(maxsize=129)
        for f in self.buffer:
            if f.get('eventSeq',0)>cursor:q.put_nowait(f)
        if self.closed:q.put_nowait(None)
        else:self.observers.add(q)
        return q


class Runs:
    def __init__(self,runtime,capacity=32):
        self.runtime,self.capacity=runtime,capacity
        self.active,self.visitors={},set()
        self.tasks=set()
        self.pending_stops=set()

    def start(self,query):
        if query.request_id in self.active:raise ValueError('当前请求已有正在执行的任务')
        if query.visitor_id in self.visitors:raise ValueError('当前访客已有正在执行的任务')
        if len(self.active)>=self.capacity:raise ValueError('Agent executor busy')
        stream=RunStream(query)
        self.active[query.request_id]=stream;self.visitors.add(query.visitor_id)
        if query.request_id in self.pending_stops:
            self.pending_stops.discard(query.request_id)
            stream.control.stop()
        async def execute():
            try:
                if hasattr(self.runtime,'subagents'):
                    await self.runtime.execute(query,stream.publish,stream.control)
                else:await self.runtime.execute(query,stream.publish)
            except asyncio.CancelledError:
                stream.control.stop()
                if hasattr(self.runtime,'subagents'):await self.runtime.subagents.settle_cancelled(stream.control)
                raise
            except Exception as exc:
                await stream.publish(frame(query.request_id,'failed',True,errorMsg='Execution persistence failed: '+type(exc).__name__,packageType='result'))
                stream.control.stop()
                if hasattr(self.runtime,'subagents'):await self.runtime.subagents.settle_cancelled(stream.control)
        stream.task=asyncio.create_task(execute(),name='reactor:'+query.request_id)
        self.tasks.add(stream.task)
        def complete(task):
            stream.close()
            if self.active.get(query.request_id) is stream:self.active.pop(query.request_id,None)
            self.visitors.discard(query.visitor_id)
            self.tasks.discard(task)
        stream.task.add_done_callback(complete)
        return stream

    def stop(self,request_id,pending=False):
        stream=self.active.get(request_id)
        if stream:return True,stream.control.stop()
        if pending:
            first=request_id not in self.pending_stops
            self.pending_stops.add(request_id)
            return True,first
        return False,False

    def inject(self,request_id,text):
        stream=self.active.get(request_id)
        if not stream or stream.control.cancelled or stream.control.root_closed:return False
        stream.control.injections.append({'text':text[:8000]})
        return True

    async def drain(self):
        if self.tasks:await asyncio.gather(*tuple(self.tasks),return_exceptions=True)
