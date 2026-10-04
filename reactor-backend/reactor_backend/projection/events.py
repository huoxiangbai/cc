"""Java-compatible data-only frames and canonical live/history envelopes."""
from collections import defaultdict
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo
from reactor_backend.models.types import encode


def frame(request_id=None, status=None, finished=False, result_map=None, **overrides):
    result = dict(status=status, response=None, responseAll=None, finished=finished,
                  useTimes=0, useTokens=0, resultMap=result_map, responseType=None,
                  traceId=None, reqId=request_id, encrypted=False, query=None,
                  messages=None, packageType=None, errorMsg=None, eventSeq=0, retryMs=None)
    result.update(overrides)
    return result


def control(request_id, package, finished=False, **extra):
    return frame(request_id, "success", finished, packageType=package,
                 response="", responseAll="", **extra)


def wire(payload):
    return ("data:" + encode(payload) + "\n\n").encode("utf-8")


def epoch(value=None):
    if isinstance(value, datetime):
        return str(int(value.replace(tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()*1000))
    return str(int(datetime.now().timestamp()*1000))


class Projector:
    def __init__(self, request_id, history=False):
        self.request_id, self.history = request_id, history
        self.agent_type = 5
        self.task_id = str(uuid4())
        self.task_order, self.event_seq = 0, 0
        self.message_order = defaultdict(int)

    def event(self, kind, message_id, values, finished=False, status="success", refs=None, at=None):
        self.task_order += 1
        self.message_order[kind] += 1
        self.event_seq += 1
        payload = dict(requestId=self.request_id, messageId=message_id, messageTime=epoch(at),
                       messageType=kind, isFinal=True, finish=kind == "result")
        payload.update(values)
        event = dict(taskId=self.task_id, taskOrder=self.task_order, messageType="plan_thought" if kind == "plan_thought" else "task",
                     messageOrder=self.message_order[kind], messageId=message_id, resultMap=payload)
        if refs:
            event["artifactRefs"] = refs
        result = frame(self.request_id, status, True if self.history else finished,
                     {"agentType": "history" if self.history else self.agent_type, "multiAgent": {}, "eventData": event})
        if not self.history:
            result.update(eventSeq=self.event_seq, packageType="result", responseType="text", response="", responseAll="")
        return result
