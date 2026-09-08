from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Input, RichLog

from agentic_data_platform.interface import AgenticService
from agentic_data_platform.tui.app import AgenticApp


def test_textual_app_mounts_focuses_prompt_and_repeats_read_actions(tmp_path: Path):
    service = AgenticService(tmp_path)

    async def exercise() -> None:
        app = AgenticApp(service)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt", Input)
            log = app.query_one("#agent-log", RichLog)
            assert prompt.has_focus
            assert log is not None

            # Repeated read-only keyboard actions must remain safe and keep the
            # application responsive on an empty/no-config project.
            await pilot.press("ctrl+d")
            await pilot.pause()
            await pilot.press("ctrl+t")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert app.query_one("#prompt", Input) is prompt

    asyncio.run(exercise())
