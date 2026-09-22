"""Pure scoring of agent decisions against benchmark checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from qa_agent_lm.benchmark.corpus import BenchmarkCase, _read_json

_ROOT = Path(__file__).resolve().parents[3] / "contracts"


@dataclass(frozen=True)
class DecisionScore:
    schema_valid: bool
    tool_correct: bool
    target_correct: bool | None
    input_correct: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class TerminalScore:
    schema_valid: bool
    terminal_correct: bool
    reasons: tuple[str, ...]


def _decision_validator() -> Draft202012Validator:
    browser = _read_json(_ROOT / "v0.1" / "browser-tool-request.schema.json")
    decision = _read_json(_ROOT / "v0.2" / "agent-decision.schema.json")
    registry = Registry().with_resource(cast(str, browser["$id"]), Resource.from_contents(browser))
    return Draft202012Validator(decision, format_checker=FormatChecker(), registry=registry)


def contains(actual: object, expected: object) -> bool:
    """Check required nested object keys; arrays and scalars require equality."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and contains(actual[key], value) for key, value in expected.items()
        )
    return actual == expected


def score_decision(case: BenchmarkCase, checkpoint_id: str, prediction: object) -> DecisionScore:
    """Score one decision against the named checkpoint, not inferred history."""
    if checkpoint_id not in case.contexts:
        raise ValueError(f"unknown checkpoint: {checkpoint_id}")
    if not _decision_validator().is_valid(prediction):
        return DecisionScore(False, False, None, False, ("invalid_schema",))
    decision = cast(dict[str, Any], prediction)
    checkpoints = cast(list[dict[str, Any]], case.data["oracle"]["checkpoints"])
    checkpoint = next(
        (item for item in checkpoints if item["checkpoint_id"] == checkpoint_id), None
    )
    if checkpoint is None:
        raise ValueError(f"unknown checkpoint: {checkpoint_id}")
    alternatives = cast(list[dict[str, Any]], checkpoint["acceptable_next"])
    matching = [item for item in alternatives if item["operation"] == decision["operation"]]
    if not matching:
        return DecisionScore(True, False, None, False, ("wrong_tool",))
    elements = cast(list[dict[str, Any]], case.contexts[checkpoint_id]["observation"]["elements"])
    target_results: list[bool | None] = []
    input_results: list[bool] = []
    for expected in matching:
        target = expected.get("target")
        if target is None:
            target_results.append(None)
        else:
            target_results.append(
                any(
                    element["element_ref"] == decision["input"].get("element_ref")
                    and element["role"] == target["role"]
                    and element["name"] == target["name"]
                    for element in elements
                )
            )
        input_results.append(
            target_results[-1] is not False
            and contains(decision["input"], expected.get("input_contains", {}))
        )
    target_correct = True if True in target_results else False if False in target_results else None
    input_correct = any(input_results)
    reasons: list[str] = []
    if target_correct is False:
        reasons.append("wrong_target")
    if not input_correct:
        reasons.append("wrong_input")
    return DecisionScore(True, True, target_correct, input_correct, tuple(reasons))


def score_terminal(case: BenchmarkCase, prediction: object) -> TerminalScore:
    """Score final pass/fail or human-help reason."""
    if not _decision_validator().is_valid(prediction):
        return TerminalScore(False, False, ("invalid_schema",))
    decision = cast(dict[str, Any], prediction)
    expected = cast(dict[str, Any], case.data["oracle"]["terminal"])
    if decision["operation"] != expected["operation"]:
        return TerminalScore(True, False, ("wrong_terminal_operation",))
    field = "outcome" if expected["operation"] == "finish" else "reason"
    if decision["input"].get(field) != expected[field]:
        return TerminalScore(True, False, ("wrong_terminal_value",))
    return TerminalScore(True, True, ())
