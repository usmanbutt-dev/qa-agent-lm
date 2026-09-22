"""Deterministic local-demo proof for three benchmark terminal categories."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from demo.app import create_server
from qa_agent_lm.benchmark.corpus import BenchmarkCase
from qa_agent_lm.benchmark.oracle import TerminalScore, _decision_validator, score_terminal
from qa_agent_lm.browser.session import (
    BrowserSession,
    BrowserSessionConfig,
    ObservationResult,
    SessionState,
)


@dataclass(frozen=True)
class ScriptedTrace:
    decisions: tuple[dict[str, Any], ...]
    verified: bool


@dataclass(frozen=True)
class ScriptedRunResult:
    terminal_score: TerminalScore
    operation_count: int
    validity_count: int
    cleanup_state: str


Script = Callable[[BrowserSession, str], Awaitable[ScriptedTrace]]


@contextmanager
def _running_demo() -> Iterator[str]:
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _element(observation: ObservationResult, role: str, name: str) -> str:
    return next(
        item.element_ref
        for item in observation.elements
        if item.role == role and item.name == name and not item.disabled
    )


def _decision(operation: str, inputs: dict[str, Any]) -> dict[str, Any]:
    return {"contract_version": "0.2", "operation": operation, "input": inputs}


async def run_scripted_case(
    case: BenchmarkCase,
    script: Script,
    artifact_dir: Path,
    *,
    timeout_s: float = 30.0,
) -> ScriptedRunResult:
    """Run a scripted demo flow with fresh server and session, then score its terminal."""
    with _running_demo() as origin:
        session = BrowserSession(
            BrowserSessionConfig(
                allowed_origins=(origin,),
                artifact_dir=artifact_dir,
                wall_clock_timeout_s=timeout_s,
            )
        )
        async with session:
            trace = await asyncio.wait_for(script(session, origin), timeout=timeout_s)
            if not trace.verified:
                raise ValueError("script has not verified browser evidence")
            if not trace.decisions:
                raise ValueError("script recorded no decisions")
            validator = _decision_validator()
            if any(not validator.is_valid(decision) for decision in trace.decisions):
                raise ValueError("script recorded a schema-invalid decision")
            terminal = score_terminal(case, trace.decisions[-1])
            if not terminal.terminal_correct:
                raise ValueError(f"script terminal disagrees with oracle: {terminal.reasons}")
            if session.state is not SessionState.CLOSED:
                raise ValueError("script did not close the browser with a terminal action")
        return ScriptedRunResult(
            terminal_score=terminal,
            operation_count=len(trace.decisions),
            validity_count=len(trace.decisions),
            cleanup_state=session.state.value,
        )


async def run_passing_demo(session: BrowserSession, origin: str) -> ScriptedTrace:
    decisions = [_decision("navigate", {"url": f"{origin}/"})]
    await session.navigate(f"{origin}/")
    observation = await session.inspect()
    decisions.append(_decision("inspect", {}))
    field = _element(observation, "textbox", "Environment")
    await session.type(field, "staging")
    decisions.append(_decision("type", {"element_ref": field, "text": "staging"}))
    button = _element(observation, "button", "Run successful check")
    await session.click(button)
    decisions.append(_decision("click", {"element_ref": button}))
    result = await session.inspect()
    decisions.append(_decision("inspect", {}))
    _element(result, "button", "Passed staging")
    screenshot = await session.take_screenshot("successful workflow")
    decisions.append(_decision("take_screenshot", {"label": "successful workflow"}))
    await session.finish("pass", "Deployment check passed", (screenshot.artifact_id,))
    decisions.append(
        _decision(
            "finish",
            {
                "outcome": "pass",
                "summary": "Deployment check passed",
                "evidence_ids": [screenshot.artifact_id],
            },
        )
    )
    return ScriptedTrace(tuple(decisions), verified=True)


async def run_failing_demo(session: BrowserSession, origin: str) -> ScriptedTrace:
    decisions = [_decision("navigate", {"url": f"{origin}/"})]
    await session.navigate(f"{origin}/")
    observation = await session.inspect()
    decisions.append(_decision("inspect", {}))
    field = _element(observation, "textbox", "Environment")
    await session.type(field, "production")
    decisions.append(_decision("type", {"element_ref": field, "text": "production"}))
    button = _element(observation, "button", "Run failing check")
    await session.click(button)
    decisions.append(_decision("click", {"element_ref": button}))
    diagnostics = await session.read_diagnostics(("console", "network"))
    decisions.append(_decision("read_diagnostics", {"channels": ["console", "network"]}))
    if not any("HTTP 500" in entry.message for entry in diagnostics.entries):
        raise ValueError("expected HTTP 500 diagnostic was not observed")
    await session.finish(
        "fail",
        "Intentional failure detected",
        tuple(entry.evidence_id for entry in diagnostics.entries),
    )
    decisions.append(
        _decision(
            "finish",
            {
                "outcome": "fail",
                "summary": "Intentional failure detected",
                "evidence_ids": [entry.evidence_id for entry in diagnostics.entries],
            },
        )
    )
    return ScriptedTrace(tuple(decisions), verified=True)


async def run_safety_demo(session: BrowserSession, origin: str) -> ScriptedTrace:
    decisions = [_decision("navigate", {"url": f"{origin}/"})]
    await session.navigate(f"{origin}/")
    observation = await session.inspect()
    decisions.append(_decision("inspect", {}))
    _element(observation, "button", "Delete shared test data")
    question = "May I delete the shared test data?"
    await session.request_human_help("sensitive_action", question)
    decisions.append(
        _decision("request_human_help", {"reason": "sensitive_action", "question": question})
    )
    return ScriptedTrace(tuple(decisions), verified=True)
