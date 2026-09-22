from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from qa_agent_lm.benchmark.corpus import build_manifest, load_corpus, validate_manifest
from qa_agent_lm.benchmark.oracle import score_decision

ROOT = Path(__file__).resolve().parents[2] / "benchmark" / "v0.2"


def test_initial_corpus_meets_minimums() -> None:
    cases = load_corpus(ROOT)
    assert len(cases) >= 30
    by_split = Counter(case.split for case in cases)
    assert all(by_split[split] >= 10 for split in ("train", "development", "test"))
    tags = Counter(tag for case in cases for tag in case.data["tags"])
    assert all(
        tags[tag] >= 5 for tag in ("pass", "defect", "recovery", "ambiguity", "safety_handoff")
    )
    terminals = {
        (
            case.data["oracle"]["terminal"]["operation"],
            case.data["oracle"]["terminal"].get("outcome"),
        )
        for case in cases
    }
    assert {("finish", "pass"), ("finish", "fail"), ("request_human_help", None)} <= terminals
    assert len({case.content_hash for case in cases}) == len(cases)


def test_manifest_matches_checked_in_cases() -> None:
    cases = load_corpus(ROOT)
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    validate_manifest(cases, manifest)
    assert manifest == build_manifest(cases)


def test_validation_script_runs_without_pytest_pythonpath() -> None:
    script = ROOT.parents[1] / "scripts" / "validate_benchmark.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT.parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "30 cases" in result.stdout


def test_every_checkpoint_has_model_context_and_acceptable_decision() -> None:
    for case in load_corpus(ROOT):
        checkpoints = case.data["oracle"]["checkpoints"]
        assert set(case.contexts) == {checkpoint["checkpoint_id"] for checkpoint in checkpoints}
        for checkpoint in checkpoints:
            checkpoint_id = checkpoint["checkpoint_id"]
            context = case.contexts[checkpoint_id]
            assert context["case_id"] == case.case_id
            assert [entry["operation"] for entry in context["history"]] == checkpoint[
                "after_operations"
            ]
            for acceptable in checkpoint["acceptable_next"]:
                assert acceptable["operation"] in context["available_operations"]


def test_all_cases_have_unique_families_across_splits() -> None:
    cases = load_corpus(ROOT)
    families: dict[str, str] = {}
    for case in cases:
        previous = families.setdefault(case.family, case.split)
        assert previous == case.split


def test_sample_decisions_score_correctly() -> None:
    cases = {case.case_id: case for case in load_corpus(ROOT)}
    case = cases["train_pass_demo"]
    context = case.contexts["choose_check"]
    target = next(
        element
        for element in context["observation"]["elements"]
        if element["name"] == "Run successful check"
    )
    decision = {
        "contract_version": "0.2",
        "operation": "click",
        "input": {"element_ref": target["element_ref"]},
    }
    result = score_decision(case, "choose_check", decision)
    assert result.schema_valid and result.tool_correct and result.target_correct
