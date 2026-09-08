"""Textual terminal interface for Agentic Data Engineering OS."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, ListItem, ListView, RichLog, Static

from agentic_data_platform.errors import safe_error
from agentic_data_platform.interface import AgenticService
from agentic_data_platform.models import ActorMode
from agentic_data_platform.security.redaction import redact, redact_string
from agentic_data_platform.tui.commands import execute, help_text


NAVIGATION = (
    "Project", "SQL", "dbt", "Airflow", "Warehouses", "Lineage", "Quality",
    "Reconciliation", "Migration", "FinOps", "Governance", "Runs", "Traces", "Sessions",
)


def _format_user_error(exc: Exception) -> str:
    error = safe_error(exc)
    return f"{error['error_type']}: {error['message']}"


class AgenticApp(App[None]):
    TITLE = "Agentic Data Engineering OS"
    SUB_TITLE = "Governed developer intelligence"
    BINDINGS = [
        ("ctrl+d", "discover", "Discover"),
        ("ctrl+t", "traces", "Traces"),
        ("ctrl+s", "sessions", "Sessions"),
        ("ctrl+q", "quit", "Quit"),
    ]
    CSS = """
    Screen { layout: vertical; }
    #workspace { height: 1fr; }
    #nav { width: 27; border-right: solid $accent; }
    #main { width: 1fr; }
    #agent-log { height: 1fr; padding: 1 2; }
    #prompt { dock: bottom; margin: 0 1 1 1; }
    #status { height: 1; dock: bottom; background: $panel; padding: 0 1; }
    """

    def __init__(
        self,
        service: AgenticService,
    ) -> None:
        super().__init__()
        self.service = service

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="workspace"):
            yield ListView(
                *(ListItem(Static(item), id=f"nav-{item.casefold()}") for item in NAVIGATION),
                id="nav",
            )
            with Vertical(id="main"):
                yield RichLog(id="agent-log", markup=True, wrap=True)
                yield Input(
                    placeholder="Ask a question or use /help",
                    id="prompt",
                )
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#agent-log", RichLog)
        log.write("[b]Agentic Data Engineering OS[/b]")
        log.write("Scanning project...")
        self._write_discovery(log)
        log.write("\n" + help_text())
        self._refresh_status()
        self.query_one("#prompt", Input).focus()

    def _refresh_status(self) -> None:
        status = self.service.status()
        provider = status["provider"] or "not configured"
        model = status["model"] or "—"
        self.query_one("#status", Static).update(
            f"Mode: {status['mode']} | Provider: {provider} | Model: {model} | "
            f"Session: {status['session_id']} | Tools: {status['tool_count']}"
        )

    def _write_discovery(self, log: RichLog | None = None) -> None:
        target = log or self.query_one("#agent-log", RichLog)
        try:
            target.write(self.service.discover_text())
        except Exception as exc:
            target.write(f"[red]Discovery error:[/red] {_format_user_error(exc)}")

    def _render_json(self, value: Any) -> None:
        self.query_one("#agent-log", RichLog).write(
            json.dumps(redact(value), indent=2, default=str)
        )

    def _render_event(self, event: dict[str, Any]) -> None:
        log = self.query_one("#agent-log", RichLog)
        name = event.get("event")
        if name == "generation.started":
            log.write(f"[cyan]Analyzing...[/cyan] step {event.get('step')}")
        elif name == "tool.started":
            approval = " · approval required" if event.get("requires_approval") else ""
            log.write(f"[yellow]→ tool[/yellow] {event.get('tool')} [{event.get('risk')}]{approval}")
        elif name == "tool.finished":
            log.write(f"[green]✓ tool[/green] {event.get('tool')} · {event.get('status')}")
        elif name == "approval.required":
            log.write(f"[bold yellow]Approval required:[/bold yellow] {event.get('tool')}")
        elif name == "generation.finished" and event.get("content"):
            log.write(redact_string(str(event["content"])))
        elif name == "session.finished" and event.get("status") == "ERROR":
            log.write(f"[red]Agent error:[/red] {redact_string(str(event.get('message') or ''))}")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        event.input.value = ""
        if not value:
            return
        log = self.query_one("#agent-log", RichLog)
        log.write(f"[bold]> {redact_string(value)}[/bold]")
        if value.startswith("/"):
            try:
                result = execute(value, self.service)
                if result.get("status") == "EXIT":
                    self.exit()
                    return
                self._render_json(result)
                self._refresh_status()
            except Exception as exc:
                log.write(f"[red]{_format_user_error(exc)}[/red]")
            return

        def callback(payload: dict[str, Any]) -> None:
            self.call_from_thread(self._render_event, payload)

        try:
            result = await asyncio.to_thread(
                self.service.ask,
                value,
                event_handler=callback,
            )
            if result.get("status") != "PASS":
                self._render_json(result)
        except Exception as exc:
            log.write(f"[red]{_format_user_error(exc)}[/red]")
        self._refresh_status()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        label = event.item.query_one(Static).render()
        self.query_one("#agent-log", RichLog).write(f"[b]{label}[/b] selected")

    def action_discover(self) -> None:
        self._write_discovery()

    def action_traces(self) -> None:
        self._render_json({"traces": self.service.traces(limit=25)})

    def action_sessions(self) -> None:
        self._render_json({"sessions": self.service.sessions(limit=25)})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project", default=".")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--mode", choices=[item.value for item in ActorMode], default=ActorMode.ANALYST.value)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = AgenticService(
        Path(args.project),
        actor_mode=ActorMode(args.mode),
        provider=args.provider,
        model=args.model,
    )
    AgenticApp(service).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
