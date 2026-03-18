"""
LegalLens Agent Service
-----------------------
Microsoft Agent Framework integration using AzureOpenAIChatClient.

Exposes a singleton AgentService that:
  - Builds a ChatClient-backed agent once at startup.
  - Registers CRUD function tools on DocumentCRUDTools so the agent can
    autonomously create, read, update, delete, and list legal documents.
  - Manages per-session conversation state via agent.create_session().
  - Supports both synchronous (run) and streaming responses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, AsyncIterator

import logger  # noqa: F401 — configure logging to logs/app.log
from agent_framework.azure import AzureOpenAIChatClient
from agent_framework import Agent, AgentSession
from azure.identity.aio import ClientSecretCredential
from pydantic import Field
from prompts import get_system_prompt
from dotenv import load_dotenv

load_dotenv()
from monday_tools import get_schema, get_unique_values, get_items_filtered, get_items_filtered_by_value_any_column, get_items_page, get_random_rows
from tracing_middleware import trace_tool_calls




app_logger = logging.getLogger(__name__)


class AgentService:
    """
    Singleton that owns the Azure OpenAI-backed agent lifecycle.

    Usage
    -----
    service = AgentService()
    await service.initialize()                       # once, on startup

    # stateless, one-shot
    text = await service.run("Summarise document abc-123")

    # stateful, multi-turn
    session_id = await service.create_session()
    text = await service.run("chat", "Summarise document abc-123")
    text = await service.run("chat", "List all contracts", session_id=session_id)

    await service.delete_session(session_id)

    # streaming
    async for chunk in service.stream("Create a brief titled 'Motion to Dismiss'"):
        print(chunk, end="", flush=True)

    await service.cleanup()                          # on shutdown
    """

    _instance: AgentService | None = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __new__(cls) -> AgentService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialised", False):
            return
        self._initialised: bool = False
        self._agent: Agent | None = None
        self._credential: ClientSecretCredential | None = None
        self._sessions: dict[str, Any] = {}
        self.system_prompt = get_system_prompt()

    async def initialize(self) -> None:
        """
        Build the Azure credential, connect the DB pool, and create the
        Agent Framework agent.  Call once at application startup.
        """
        async with self._lock:
            if self._initialised:
                return

            # Production credential: service-principal, not AzureCliCredential,
            # so it works in hosted environments without az login.
            # self._credential = ClientSecretCredential(
            #     tenant_id=settings.TENANT_ID,
            #     client_id=settings.CLIENT_ID,
            #     client_secret=settings.CLIENT_SECRET,
            # )
            
            self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            self.api_version = os.getenv("AZURE_OPENAI_API_VERSION")
            self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
            self.deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT")

            client = AzureOpenAIChatClient(
                        # credential=self._credential,
                        api_version=self.api_version, 
                        endpoint=self.endpoint,
                        api_key=self.api_key, 
                        deployment_name=self.deployment_name
                    )

            self._agent = client.as_agent(
                name="MondayBIAgent",
                instructions=self.system_prompt,
                tools=[get_schema, get_unique_values, get_items_filtered, get_items_filtered_by_value_any_column, get_items_page, get_random_rows],
                middleware=[trace_tool_calls],
            )        

            self._initialised = True
            app_logger.info("AgentService initialised with AzureOpenAIChatClient")

    async def cleanup(self) -> None:
        """Release credential and close any open sessions. Call on shutdown."""
        # for session in self._sessions.values():
        #     try:
        #         await session.close()
        #     except Exception:
        #         pass
        self._sessions.clear()

        if self._credential:
            await self._credential.close()
            self._credential = None

        self._initialised = False
        app_logger.info("AgentService cleaned up")


    async def create_session(self, serialized=None) -> str:
        """
        Allocate a new multi-turn conversation session.
        Returns a session_id that callers must pass to run() / stream().
        """
        self._require_ready()
        session_id = str(uuid.uuid4())
        if not serialized:
            self._sessions[session_id] = self._agent.create_session()  # type: ignore[union-attr]
        else:
            self._sessions[session_id] = AgentSession.from_dict(serialized)    
        
        app_logger.debug("Session created: %s", session_id)
        return session_id

    async def delete_session(self, session_id: str) -> None:
        """Close and discard a previously created session."""
        session = self._sessions.pop(session_id, None)
        # if session is not None:
        #     try:
        #         await session.close()
        #     except Exception as e:
        #         pass
        app_logger.debug("Session deleted: %s", session_id)


    def list_sessions(self) -> list[str]:
        """Return all active session IDs."""
        return list(self._sessions.keys())

    async def run(
        self,
        query: str,
        *,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Run the agent and return the complete text response.

        Parameters
        ----------
        query:      Natural-language instruction for the agent.
        session_id: If provided, continues the existing conversation.
        **kwargs:   Extra kwargs forwarded to agent.run() (e.g. injected
                    tool arguments like user_id).
        """
        self._require_ready()

        run_kwargs: dict[str, Any] = dict(kwargs)
        if session_id is not None:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError(f"Unknown session_id: {session_id!r}")
            run_kwargs["session"] = session

        response = await self._agent.run(query, **run_kwargs)  # type: ignore[union-attr]
        
        return response.text

    async def stream(
        self,
        query: str,
        *,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """
        Run the agent with streaming and yield text chunks as they arrive.

        Parameters
        ----------
        query:      Natural-language instruction for the agent.
        session_id: If provided, continues the existing conversation.
        **kwargs:   Extra kwargs forwarded to agent.run().
        """
        self._require_ready()

        run_kwargs: dict[str, Any] = {"stream": True, **kwargs}
        if session_id is not None:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError(f"Unknown session_id: {session_id!r}")
            run_kwargs["session"] = session

        async for chunk in self._agent.run(query, **run_kwargs):  # type: ignore[union-attr]
            if chunk.text:
                yield chunk.text

    def _require_ready(self) -> None:
        if not self._initialised or not self._agent:
            raise RuntimeError(
                "AgentService is not initialised. "
                "Ensure `await agent_service.initialize()` is called at startup."
            )

    @property
    def is_ready(self) -> bool:
        return self._initialised


agent_service = AgentService()