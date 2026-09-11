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
    text_block,
    tool_content,
    update_tool_call,
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
    PermissionOption,
    ResourceContentBlock,
    SseMcpServer,
    TextContentBlock,
)

from agentic_data_platform.security.redaction import redact
from agentic_data_platform.sdk import ADEClient, LocalAgentSession
from agentic_data_platform.tools.registry import ToolRegistry


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


def _permission_allowed(response: Any, option_id: str = "allow_once") -> bool:
    outcome = getattr(response, "outcome", None)
    return (
        getattr(outcome, "outcome", None) == "selected"
        and getattr(outcome, "option_id", None) == option_id
    )


def _tool_kind(risk: str) -> str:
    return "execute" if risk in {"mutating", "destructive"} else "other"


class ADEACPAgent(Agent):
    """Persistent ACP adapter backed by the real ADE embedded SDK."""

    _conn: Client

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.registry = registry
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
        sdk = ADEClient(root, registry=self.registry, provider=self.provider, model=self.model)
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
        session = ADEClient(
            root,
            registry=self.registry,
            provider=self.provider,
            model=self.model,
        ).session(
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

    async def _emit_message_chunks(self, session_id: str, text: str, *, chunk_chars: int = 1200) -> bool:
        """Deliver a completed ADE response through ACP message chunks.

        This is protocol-level buffered chunk delivery; it is intentionally not represented
        as provider token streaming because the current ADE provider runtime returns a completed
        response object.
        """

        value = str(text)
        if not value:
            return True
        for start in range(0, len(value), chunk_chars):
            if session_id in self._cancelled:
                return False
            await self._conn.session_update(
                session_id,
                AgentMessageChunk(content=TextContentBlock(text=value[start : start + chunk_chars])),
            )
        return True

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
        emitted = await self._emit_message_chunks(session_id, text)
        if not emitted:
            self._cancelled.discard(session_id)
            return PromptResponse(stop_reason="cancelled")
        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        del kwargs
        self._cancelled.add(session_id)

    async def _invoke_tool_with_permission(self, session_id: str, params: dict[str, Any]) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"unknown ACP session: {session_id}")
        tool = str(params.get("tool") or "").strip()
        if not tool:
            raise ValueError("tool is required")
        args = params.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError("args must be an object")
        invocation_kwargs = {
            "operation": params.get("operation") or tool,
            "environment": params.get("environment") or "dev",
            "platform": params.get("platform"),
            "scopes": tuple(params.get("scopes") or ()),
            "dry_run": bool(params.get("dry_run", False)),
        }
        preview = session.invoke_tool(tool, args, **invocation_kwargs)
        if preview.get("status") != "APPROVAL_REQUIRED":
            return preview

        approval = preview.get("approval") or {}
        fingerprint = str(approval.get("fingerprint") or "")
        if len(fingerprint) != 64:
            raise RuntimeError("ADE approval request did not include a valid fingerprint")
        safe_input = redact(
            {
                "tool": tool,
                "operation": approval.get("operation"),
                "risk": approval.get("risk"),
                "environment": approval.get("environment"),
                "args": args,
                "platform": approval.get("platform"),
                "scopes": approval.get("scopes"),
                "fingerprint": fingerprint,
            }
        )
        tool_call = update_tool_call(
            f"ade-approval-{fingerprint[:16]}",
            title=f"Approve ADE tool: {tool}",
            kind=_tool_kind(str(approval.get("risk") or "")),
            status="pending",
            content=[
                tool_content(
                    text_block(
                        "ADE requires approval for this exact tool request. "
                        f"Fingerprint: {fingerprint}"
                    )
                )
            ],
            raw_input=safe_input,
        )
        options = [
            PermissionOption(option_id="allow_once", kind="allow_once", name="Allow this exact request"),
            PermissionOption(option_id="deny", kind="reject_once", name="Deny"),
        ]
        response = await self._conn.request_permission(
            session_id=session_id,
            tool_call=tool_call,
            options=options,
        )
        if not _permission_allowed(response):
            return {
                "status": "DENIED",
                "session_id": session_id,
                "tool": tool,
                "approval_fingerprint": fingerprint,
                "acp_permission": "denied",
            }
        result = session.invoke_tool(
            tool,
            args,
            **invocation_kwargs,
            approval_callback=lambda request: request.fingerprint == fingerprint,
        )
        if result.get("approval_fingerprint") != fingerprint:
            raise RuntimeError("executed tool approval fingerprint changed after ACP approval")
        return {**result, "acp_permission": "allow_once"}

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
                "streaming": "buffered_acp_message_chunks",
                "providerCancellation": "not_supported_by_current_provider_runtime",
            }
        if method == "ade/tool/invoke":
            session_id = str(params.get("sessionId") or params.get("session_id") or "")
            if not session_id:
                raise ValueError("sessionId is required")
            return await self._invoke_tool_with_permission(session_id, params)
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