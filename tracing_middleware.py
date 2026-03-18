"""
Function middleware that records tool invocations for observability.
Appends to the list passed as trace_collector in agent.run(**kwargs).
"""
from __future__ import annotations

import time
from agent_framework import function_middleware
from agent_framework import FunctionInvocationContext


@function_middleware
async def trace_tool_calls(context: FunctionInvocationContext, call_next):
    """Record tool name, arguments summary, duration, and status to context.kwargs['trace_collector']."""
    trace_collector = (context.kwargs or {}).get("trace_collector")
    if not isinstance(trace_collector, list):
        await call_next()
        return

    tool_name = getattr(context.function, "name", str(context.function))
    args_repr = str(context.arguments)[:300] if context.arguments else ""
    t0 = time.perf_counter()
    try:
        await call_next()
        duration_ms = (time.perf_counter() - t0) * 1000
        trace_collector.append({
            "tool": tool_name,
            "duration_ms": round(duration_ms, 2),
            "arguments": args_repr,
            "status": "ok",
            "error": None,
        })
    except Exception as e:
        duration_ms = (time.perf_counter() - t0) * 1000
        trace_collector.append({
            "tool": tool_name,
            "duration_ms": round(duration_ms, 2),
            "arguments": args_repr,
            "status": "error",
            "error": str(e),
        })
        raise
