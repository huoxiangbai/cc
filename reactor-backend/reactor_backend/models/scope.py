"""Attempt recording stays with the caller, including fallback and child identity."""
from contextvars import ContextVar

model_scope = ContextVar("reactor_model_scope", default=None)
agent_scope = ContextVar("reactor_agent_scope", default=None)
