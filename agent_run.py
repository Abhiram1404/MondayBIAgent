import asyncio
import logging

import logger  # noqa: F401 — configure logging to logs/app.log
from AgentService import agent_service

logger = logging.getLogger(__name__)


async def _get_ai_response_async(query: str, session_id: str | None, trace_collector: list | None):
    if session_id is None:
        session_id = await agent_service.create_session()
    run_kwargs = {"session_id": session_id}
    if trace_collector is not None:
        run_kwargs["trace_collector"] = trace_collector
    response = await agent_service.run(query, **run_kwargs)
    return response, session_id


def get_ai_response(query: str, session_id: str = None, trace_collector: list = None):
    """
    Run the agent and return (response_text, session_id).
    If trace_collector is a list, it will be filled with tool call traces (tool, duration_ms, status, etc.).
    """
    try:
        return asyncio.run(_get_ai_response_async(query, session_id, trace_collector))
    except Exception as e:
        logger.error(f"Error getting AI response: {e}")
        raise