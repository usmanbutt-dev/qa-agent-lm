from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from qa_agent_lm.benchmark.corpus import load_corpus
from qa_agent_lm.benchmark.scripted import (
    Script,
    ScriptedTrace,
    run_failing_demo,
    run_passing_demo,
    run_safety_demo,
    run_scripted_case,
)
from qa_agent_lm.browser.session import BrowserSession, SessionState

ROOT = Path(__file__).resolve().parents[2] / "benchmark" / "v0.2"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "script"),
    [
        ("train_pass_demo", run_passing_demo),
        ("development_defect_demo", run_failing_demo),
        ("test_safety_demo", run_safety_demo),
    ],
)
async def test_scripted_demo_is_repeatable(case_id: str, script: Script, tmp_path: Path) -> None:
    case = next(case for case in load_corpus(ROOT) if case.case_id == case_id)
    first = await run_scripted_case(case, script, tmp_path / "first")
    second = await run_scripted_case(case, script, tmp_path / "second")
    assert first == second
    assert first.terminal_score.terminal_correct
    assert first.cleanup_state == "closed"
    assert first.validity_count == first.operation_count


@pytest.mark.asyncio
async def test_unverified_finish_is_rejected(tmp_path: Path) -> None:
    case = next(case for case in load_corpus(ROOT) if case.case_id == "train_pass_demo")

    async def unverified(session: object, origin: str) -> ScriptedTrace:
        return ScriptedTrace(
            decisions=(
                {
                    "contract_version": "0.2",
                    "operation": "finish",
                    "input": {"outcome": "pass", "summary": "Claim"},
                },
            ),
            verified=False,
        )

    with pytest.raises(ValueError, match="verified"):
        await run_scripted_case(case, unverified, tmp_path)


@pytest.mark.asyncio
async def test_timeout_cleans_up_server(tmp_path: Path) -> None:
    case = next(case for case in load_corpus(ROOT) if case.case_id == "train_pass_demo")
    sessions: list[BrowserSession] = []

    async def slow(session: BrowserSession, origin: str) -> ScriptedTrace:
        sessions.append(session)
        await asyncio.sleep(0.05)
        return ScriptedTrace(decisions=(), verified=False)

    with pytest.raises(TimeoutError):
        await run_scripted_case(case, slow, tmp_path, timeout_s=0.01)
    assert sessions[0].state is SessionState.CLOSED


@pytest.mark.asyncio
async def test_malformed_scripted_decision_closes_browser(tmp_path: Path) -> None:
    case = next(case for case in load_corpus(ROOT) if case.case_id == "train_pass_demo")
    sessions: list[BrowserSession] = []

    async def malformed(session: BrowserSession, origin: str) -> ScriptedTrace:
        sessions.append(session)
        return ScriptedTrace(
            decisions=({"contract_version": "0.2", "operation": "click", "input": {}},),
            verified=True,
        )

    with pytest.raises(ValueError, match="schema-invalid"):
        await run_scripted_case(case, malformed, tmp_path)
    assert sessions[0].state is SessionState.CLOSED
