from __future__ import annotations

from typing import Any

import pytest

from qa_agent_lm.benchmark.corpus import BenchmarkCase
from qa_agent_lm.benchmark.oracle import contains, score_decision, score_terminal


@pytest.fixture
def click_case() -> BenchmarkCase:
    context: dict[str, Any] = {
        "contract_version": "0.2",
        "case_id": "case_click",
        "objective": "Save the form.",
        "observation": {
            "observation_id": "obs_000001",
            "url": "http://127.0.0.1:8000/",
            "elements": [
                {
                    "element_ref": "el_000001_0001",
                    "role": "button",
                    "name": "Save",
                    "disabled": False,
                },
                {
                    "element_ref": "el_000001_0002",
                    "role": "button",
                    "name": "Cancel",
                    "disabled": False,
                },
            ],
            "truncated": False,
        },
        "history": [],
        "available_operations": ["click", "inspect", "finish"],
        "limits": {"remaining_steps": 4, "remaining_time_ms": 10000},
    }
    return BenchmarkCase(
        case_id="case_click",
        split="train",
        family="save_form",
        data={
            "oracle": {
                "checkpoints": [
                    {
                        "checkpoint_id": "choose",
                        "after_operations": [],
                        "acceptable_next": [
                            {"operation": "click", "target": {"role": "button", "name": "Save"}},
                            {"operation": "inspect"},
                        ],
                    }
                ],
                "terminal": {"operation": "finish", "outcome": "pass"},
                "max_steps": 4,
            }
        },
        contexts={"choose": context},
        content_hash="hash",
        context_hashes={"choose": "context_hash"},
        path="train/case_click.json",
    )


@pytest.mark.parametrize(
    ("prediction", "expected_tool", "expected_target"),
    [
        ({"contract_version": "0.2", "operation": "inspect", "input": {}}, True, None),
        (
            {
                "contract_version": "0.2",
                "operation": "click",
                "input": {"element_ref": "el_000001_0001"},
            },
            True,
            True,
        ),
        (
            {
                "contract_version": "0.2",
                "operation": "click",
                "input": {"element_ref": "el_000001_0002"},
            },
            True,
            False,
        ),
        (
            {
                "contract_version": "0.2",
                "operation": "click",
                "input": {"element_ref": "el_000000_0001"},
            },
            True,
            False,
        ),
        (
            {
                "contract_version": "0.2",
                "operation": "click",
                "input": {"element_ref": "el_000001_9999"},
            },
            True,
            False,
        ),
        (
            {
                "contract_version": "0.2",
                "operation": "take_screenshot",
                "input": {"label": "state"},
            },
            False,
            None,
        ),
    ],
)
def test_scores_tool_and_current_observation_target(
    click_case: BenchmarkCase,
    prediction: dict[str, object],
    expected_tool: bool,
    expected_target: bool | None,
) -> None:
    score = score_decision(click_case, "choose", prediction)
    assert score.schema_valid is True
    assert score.tool_correct is expected_tool
    assert score.target_correct is expected_target
    assert score == score_decision(click_case, "choose", prediction)


def test_rejects_invalid_decision_before_scoring(click_case: BenchmarkCase) -> None:
    score = score_decision(
        click_case,
        "choose",
        {"contract_version": "0.2", "operation": "click", "input": {"selector": "#save"}},
    )
    assert score.schema_valid is False
    assert score.tool_correct is False
    assert "invalid_schema" in score.reasons


def test_unknown_checkpoint_is_an_error(click_case: BenchmarkCase) -> None:
    with pytest.raises(ValueError, match="checkpoint"):
        score_decision(
            click_case, "missing", {"contract_version": "0.2", "operation": "inspect", "input": {}}
        )


def test_nested_required_input_uses_structural_containment() -> None:
    assert contains({"a": {"b": 2, "c": 3}}, {"a": {"b": 2}}) is True
    assert contains({"a": {"b": 2}}, {"a": {"b": 3}}) is False
    assert contains({"values": [1, 2]}, {"values": [1]}) is False


def test_input_contains_mismatch_rejects_candidate(click_case: BenchmarkCase) -> None:
    click_case.data["oracle"]["checkpoints"][0]["acceptable_next"][0]["input_contains"] = {
        "element_ref": "el_000001_0002"
    }
    score = score_decision(
        click_case,
        "choose",
        {
            "contract_version": "0.2",
            "operation": "click",
            "input": {"element_ref": "el_000001_0001"},
        },
    )
    assert score.input_correct is False


def test_target_and_input_must_match_same_alternative(click_case: BenchmarkCase) -> None:
    alternatives = click_case.data["oracle"]["checkpoints"][0]["acceptable_next"]
    alternatives[0]["input_contains"] = {"element_ref": "el_000001_0002"}
    alternatives[1] = {
        "operation": "click",
        "target": {"role": "button", "name": "Cancel"},
        "input_contains": {"element_ref": "el_000001_0001"},
    }
    score = score_decision(
        click_case,
        "choose",
        {
            "contract_version": "0.2",
            "operation": "click",
            "input": {"element_ref": "el_000001_0001"},
        },
    )
    assert score.input_correct is False


@pytest.mark.parametrize(
    ("prediction", "expected"),
    [
        (
            {
                "contract_version": "0.2",
                "operation": "finish",
                "input": {"outcome": "pass", "summary": "Verified", "evidence_ids": []},
            },
            True,
        ),
        (
            {
                "contract_version": "0.2",
                "operation": "finish",
                "input": {"outcome": "fail", "summary": "Failed", "evidence_ids": []},
            },
            False,
        ),
        ({"contract_version": "0.2", "operation": "inspect", "input": {}}, False),
    ],
)
def test_scores_finish_outcome(
    click_case: BenchmarkCase, prediction: dict[str, object], expected: bool
) -> None:
    score = score_terminal(click_case, prediction)
    assert score.schema_valid is True
    assert score.terminal_correct is expected


def test_scores_human_help_reason(click_case: BenchmarkCase) -> None:
    click_case.data["oracle"]["terminal"] = {
        "operation": "request_human_help",
        "reason": "sensitive_action",
    }
    correct = {
        "contract_version": "0.2",
        "operation": "request_human_help",
        "input": {"reason": "sensitive_action", "question": "May I proceed?"},
    }
    wrong = {
        "contract_version": "0.2",
        "operation": "request_human_help",
        "input": {"reason": "blocked", "question": "May I proceed?"},
    }
    assert score_terminal(click_case, correct).terminal_correct is True
    assert score_terminal(click_case, wrong).terminal_correct is False
