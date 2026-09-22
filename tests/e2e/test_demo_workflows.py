from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from demo.app import create_server
from qa_agent_lm.browser.errors import WallClockTimeoutError
from qa_agent_lm.browser.session import (
    BrowserSession,
    BrowserSessionConfig,
    ObservationResult,
    SessionState,
)


@contextmanager
def running_demo() -> Iterator[str]:
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def by_name(observation: ObservationResult, name: str) -> str:
    return next(element.element_ref for element in observation.elements if element.name == name)


@pytest.mark.asyncio
async def test_success_workflow_closes_with_screenshot_evidence(tmp_path: Path) -> None:
    with running_demo() as origin:
        session = BrowserSession(
            BrowserSessionConfig(allowed_origins=(origin,), artifact_dir=tmp_path)
        )
        await session.start()
        await session.navigate(f"{origin}/")
        observation = await session.inspect()
        await session.type(by_name(observation, "Environment"), "staging")
        await session.click(by_name(observation, "Run successful check"))
        result_observation = await session.inspect()
        assert by_name(result_observation, "Passed staging")
        screenshot = await session.take_screenshot("successful workflow")

        result = await session.finish("pass", "Deployment check passed", (screenshot.artifact_id,))

    assert result.outcome == "pass"
    assert result.state == "finished"
    assert session.state is SessionState.CLOSED
    assert (tmp_path / "artifact_000001.png").is_file()


@pytest.mark.asyncio
async def test_failure_workflow_collects_diagnostics_and_closes(tmp_path: Path) -> None:
    with running_demo() as origin:
        session = BrowserSession(
            BrowserSessionConfig(allowed_origins=(origin,), artifact_dir=tmp_path)
        )
        await session.start()
        await session.navigate(f"{origin}/")
        observation = await session.inspect()
        await session.type(by_name(observation, "Environment"), "production")
        await session.click(by_name(observation, "Run failing check"))
        diagnostics = await session.read_diagnostics(("console", "network"))
        screenshot = await session.take_screenshot("failed workflow")
        evidence_ids = (
            *(entry.evidence_id for entry in diagnostics.entries),
            screenshot.artifact_id,
        )

        result = await session.finish("fail", "Intentional failure detected", evidence_ids)

    assert diagnostics.entries
    assert any("HTTP 500" in entry.message for entry in diagnostics.entries)
    assert result.outcome == "fail"
    assert session.state is SessionState.CLOSED


@pytest.mark.asyncio
async def test_ambiguous_action_requests_human_help_and_closes(tmp_path: Path) -> None:
    with running_demo() as origin:
        session = BrowserSession(
            BrowserSessionConfig(allowed_origins=(origin,), artifact_dir=tmp_path)
        )
        await session.start()
        await session.navigate(f"{origin}/")
        observation = await session.inspect()
        assert by_name(observation, "Delete shared test data")

        result = await session.request_human_help(
            "sensitive_action", "May I delete the shared test data?"
        )

    assert result.state == "paused"
    assert session.state is SessionState.CLOSED


@pytest.mark.asyncio
async def test_timeout_path_still_cleans_up(tmp_path: Path) -> None:
    with running_demo() as origin:
        session = BrowserSession(
            BrowserSessionConfig(
                allowed_origins=(origin,),
                artifact_dir=tmp_path,
                wall_clock_timeout_s=0.01,
            )
        )
        with pytest.raises(WallClockTimeoutError):
            async with session:
                await asyncio.sleep(0.02)
                await session.navigate(f"{origin}/")

    assert session.state is SessionState.CLOSED
