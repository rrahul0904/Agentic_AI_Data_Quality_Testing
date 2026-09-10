"""Agent Client Protocol (ACP) server for ADE.

The process speaks the official ACP JSON-RPC protocol over stdio via the upstream
`agent-client-protocol` Python SDK. Editors such as Zed, JetBrains integrations and
Neovim ACP clients can spawn `ade acp serve` or the `ade-acp` entrypoint.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Any

from acp import (
    PROTOCOL_VERSION,
    Agent,
    AuthenticateResponse,
    InitializeResponse,
    LoadSessionResponse,
    NewSessionResponse,
    PromptResponse,
    SetSessionModeResponse,
    run_agent,
)
from acp.interfaces import Client
from acp.schema import (
    AgentCapabilities,
    AgentMessageChunk,
    ClientCapabilities,
    EmbeddedResourceContentBlock,
    HttpMcpServer,
    ImageContentBlock,
    Implementation,
    McpServerStdio,
    ResourceContentBlock,
    SseMcpServer,
    TextContentBlock,
)

from agentic_data_platform.sdk import ADEClient, LocalAgentSession


_MODE_IDS = {"agent", "plan", "ask", "edit", "code"}


def _prompt_text(blocks: list[Any]) -> str:
    values: list[str] = []
    for block in blocks:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            values.append(text)
            continue
        resource = getattr(block, "resource", None)
        resource_text = getattr(resource, "text", None)
        if isinstance(resource_text, str) and resource_text.strip():
            values.append(resource_text)
    return "\n\n".join(values).strip()


class ADEACPAgent(Agent):
    """Persistent ACP adapter backed by the real ADE embedded SDK."""

    _conn: Client

    def __init__(self, *, provider: str | None = None, model: str | None = None) -> None:
        self.provider = provider
        self.model = model
        self._sessions: dict[str, LocalAgentSession] = {}
        self._roots: dict[str, Path] = {}
        self._modes: dict[str, str] = {}
        self._cancelled: set[str] = set()

    def on_connect(self, conn: Client) -> None:
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        del protocol_version, client_capabilities, client_info, kwargs
        return InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_capabilities=AgentCapabilities(),
            agent_info=Implementation(
                name="ade",
                title="Agentic Data Engineering OS",
                version="0.3.0",
            ),
        )

    async def authenticate(self, method_id: str, **kwargs: Any) -> AuthenticateResponse | None:
        del method_id, kwargs
        # Provider credentials remain external environment/config references; ACP never
        # receives raw warehouse or LLM secrets from ADE.
        return AuthenticateResponse()

    async def new_session(
        self,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        del additional_directories, mcp_servers, kwargs
        root = Path(cwd).expanduser().resolve()
        sdk = ADEClient(root, provider=self.provider, model=self.model)
        session = sdk.session(auto_index=True)
        self._sessions[session.session_id] = session
        self._roots[session.session_id] = root
        self._modes[session.session_id] = "agent"
        return NewSessionResponse(session_id=session.session_id, modes=None)

    async def load_session(
        self,
        cwd: str,
        session_id: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> LoadSessionResponse | None:
        del additional_directories, mcp_servers, kwargs
        root = Path(cwd).expanduser().resolve()
        session = ADEClient(root, provider=self.provider, model=self.model).session(
            session_id=session_id,
            auto_index=False,
        )
        self._sessions[session_id] = session
        self._roots[session_id] = root
        self._modes.setdefault(session_id, "agent")
        return LoadSessionResponse()

    async def set_session_mode(
        self,
        session_id: str,
        mode_id: str,
        **kwargs: Any,
    ) -> SetSessionModeResponse | None:
        del kwargs
        if session_id not in self._sessions:
            raise KeyError(f"unknown ACP session: {session_id}")
        normalized = str(mode_id).casefold()
        if normalized not in _MODE_IDS:
            raise ValueError(f"unsupported ADE mode: {mode_id}")
        self._modes[session_id] = normalized
        return SetSessionModeResponse()

    async def prompt(
        self,
        session_id: str,
        prompt: list[
            TextContentBlock
            | ImageContentBlock
            | ResourceContentBlock
            | EmbeddedResourceContentBlock
        ],
        **kwargs: Any,
    ) -> PromptResponse:
        del kwargs
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"unknown ACP session: {session_id}")
        question = _prompt_text(prompt)
        if not question:
            await self._conn.session_update(
                session_id,
                AgentMessageChunk(content=TextContentBlock(text="ADE received no textual prompt content.")),
            )
            return PromptResponse(stop_reason="end_turn")
        if session_id in self._cancelled:
            self._cancelled.discard(session_id)
            return PromptResponse(stop_reason="cancelled")

        mode = self._modes.get(session_id, "agent")
        contextual_question = question if mode == "agent" else f"Interaction mode: {mode}.\n\n{question}"
        result = await asyncio.to_thread(session.prompt, contextual_question)
        if session_id in self._cancelled:
            self._cancelled.discard(session_id)
            return PromptResponse(stop_reason="cancelled")

        if result.get("status") == "PASS":
            text = str(result.get("response") or "")
        else:
            text = str(result.get("error") or result.get("status") or "ADE agent request failed")
        await self._conn.session_update(
            session_id,
            AgentMessageChunk(content=TextContentBlock(text=text)),
        )
        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        del kwargs
        self._cancelled.add(session_id)

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "ade/session/evidence":
            session_id = str(params.get("sessionId") or params.get("session_id") or "")
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"unknown ACP session: {session_id}")
            return {
                "sessionId": session_id,
                "mode": self._modes.get(session_id, "agent"),
                "history": session.history(),
                "projectRoot": str(self._roots[session_id]),
            }
        return {"status": "UNSUPPORTED", "method": method}

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        del method, params


async def _serve(*, provider: str | None = None, model: str | None = None) -> None:
    await run_agent(ADEACPAgent(provider=provider, model=model))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ade-acp", description="Serve ADE over Agent Client Protocol stdio")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.WARNING))
    asyncio.run(_serve(provider=args.provider, model=args.model))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
