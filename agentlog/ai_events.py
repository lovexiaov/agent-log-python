"""AI interaction events (Schema v1.4).

Convenience helpers that emit the six standardized AI ``event_type`` values
with the canonical payload vocabulary (snake_case). They go through the
process-wide singleton, mirrored on :class:`agentlog.Logger.record`.

These are explicit, business-side calls (``agent_auto=False``) — the framework
only prepares the data; the caller decides where/when to record an LLM call.
"""

from agentlog.coretypes import EventType


def _payload(**fields):
    """Build a payload dict, dropping keys whose value is ``None``."""
    return {k: v for k, v in fields.items() if v is not None}


def record_ai_request(model, prompt_text, *, provider=None, system_prompt=None,
                      messages_count=None, request_id=None, **extra):
    """Emit ``ai_request_initiated`` for the start of an LLM call."""
    payload = _payload(model=model, provider=provider, prompt_text=prompt_text,
                       system_prompt=system_prompt, messages_count=messages_count,
                       request_id=request_id)
    payload.update(extra)
    from agentlog.agentlog import instance
    instance().logger.record("info", EventType.AI_REQUEST_INITIATED,
                             "ai request initiated", category="ai", payload=payload)


def record_ai_response(model, total_tokens, *, provider=None, response_length=None,
                      prompt_tokens=None, completion_tokens=None, finish_reason=None,
                      latency_ms=None, request_id=None, **extra):
    """Emit ``ai_response_received`` with token usage for a completed call."""
    payload = _payload(model=model, provider=provider, response_length=response_length,
                       prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                       total_tokens=total_tokens, finish_reason=finish_reason,
                       latency_ms=latency_ms, request_id=request_id)
    payload.update(extra)
    from agentlog.agentlog import instance
    instance().logger.record("info", EventType.AI_RESPONSE_RECEIVED,
                             "ai response received", category="ai", payload=payload)


def record_ai_tool_call(tool_name, tool_arguments, *, request_id=None, **extra):
    """Emit ``ai_tool_call_initiated`` describing a tool the model wants to use."""
    payload = _payload(tool_name=tool_name, tool_arguments=tool_arguments,
                       request_id=request_id)
    payload.update(extra)
    from agentlog.agentlog import instance
    instance().logger.record("info", EventType.AI_TOOL_CALL_INITIATED,
                             "ai tool call initiated", category="ai", payload=payload)


def record_ai_tool_result(tool_name, ok, *, tool_call_latency_ms=None,
                          request_id=None, **extra):
    """Emit ``ai_tool_call_completed`` for a finished tool invocation."""
    payload = _payload(tool_name=tool_name, ok=ok,
                       tool_call_latency_ms=tool_call_latency_ms,
                       request_id=request_id)
    payload.update(extra)
    from agentlog.agentlog import instance
    instance().logger.record("info", EventType.AI_TOOL_CALL_COMPLETED,
                             "ai tool call completed", category="ai", payload=payload)


def record_ai_guardrail(guardrail_type, reason, *, request_id=None, **extra):
    """Emit ``ai_guardrail_triggered`` (warn) when a safeguard fires."""
    payload = _payload(guardrail_type=guardrail_type, reason=reason,
                       request_id=request_id)
    payload.update(extra)
    from agentlog.agentlog import instance
    instance().logger.record("warn", EventType.AI_GUARDRAIL_TRIGGERED,
                             "ai guardrail triggered", category="ai", payload=payload)


def record_ai_error(error_type, message, *, stack=None, request_id=None, **extra):
    """Emit ``ai_error`` reusing the v1.3 exception vocabulary."""
    payload = _payload(exception=error_type, exception_message=message, stack=stack,
                       mechanism="handled", request_id=request_id)
    payload.update(extra)
    from agentlog.agentlog import instance
    instance().logger.record("error", EventType.AI_ERROR,
                             "ai interaction error", category="ai", payload=payload)
