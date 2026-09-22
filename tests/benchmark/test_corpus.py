from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from qa_agent_lm.benchmark.corpus import build_manifest, load_corpus, validate_manifest


def _case(case_id: str, split: str, objective: str) -> dict[str, object]:
    return {
        "contract_version": "0.2",
        "case_id": case_id,
        "title": case_id,
        "objective": objective,
        "split": split,
        "tags": ["pass"],
        "setup": {"start_path": "/", "seed": {}},
        "oracle": {
            "checkpoints": [
                {
                    "checkpoint_id": "start",
                    "after_operations": [],
                    "acceptable_next": [{"operation": "inspect"}],
                }
            ],
            "terminal": {"operation": "finish", "outcome": "pass"},
            "max_steps": 5,
        },
    }


def _context(case_id: str, objective: str) -> dict[str, object]:
    return {
        "contract_version": "0.2",
        "case_id": case_id,
        "objective": objective,
        "observation": {
            "observation_id": "obs_000001",
            "url": "http://127.0.0.1:8000/",
            "elements": [],
            "truncated": False,
        },
        "history": [],
        "available_operations": ["inspect", "finish"],
        "limits": {"remaining_steps": 5, "remaining_time_ms": 10000},
    }


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture
def corpus_root(tmp_path: Path) -> Path:
    _write(tmp_path / "families.json", {"train_case_001": "family_a", "test_case_001": "family_b"})
    for case_id, split, objective in (
        ("train_case_001", "train", "Check alpha."),
        ("test_case_001", "test", "Check beta."),
    ):
        _write(tmp_path / split / f"{case_id}.json", _case(case_id, split, objective))
        _write(
            tmp_path / split / f"{case_id}.start.context.json",
            _context(case_id, objective),
        )
    return tmp_path


def test_loads_sorted_cases_and_hashes_raw_bytes(corpus_root: Path) -> None:
    cases = load_corpus(corpus_root)
    assert tuple(case.case_id for case in cases) == ("test_case_001", "train_case_001")
    expected = hashlib.sha256(
        (corpus_root / "train" / "train_case_001.json").read_bytes()
    ).hexdigest()
    assert cases[1].content_hash == expected
    assert cases[1].contexts["start"]["case_id"] == "train_case_001"


def test_rejects_cross_split_family(corpus_root: Path) -> None:
    _write(
        corpus_root / "families.json", {"train_case_001": "family_a", "test_case_001": "family_a"}
    )
    with pytest.raises(ValueError, match="workflow family"):
        load_corpus(corpus_root)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("wrong_split", "split"),
        ("wrong_context_id", "case_id"),
        ("missing_checkpoint", "checkpoint"),
        ("unknown_json", "unknown"),
        ("malformed_json", "JSON"),
        ("invalid_case", "schema"),
        ("duplicate_id", "case_id"),
        ("missing_family", "families"),
        ("normalized_duplicate", "objective"),
    ],
)
def test_rejects_invalid_corpus(corpus_root: Path, mutation: str, message: str) -> None:
    case_path = corpus_root / "train" / "train_case_001.json"
    context_path = corpus_root / "train" / "train_case_001.start.context.json"
    case = json.loads(case_path.read_text(encoding="utf-8"))
    context = json.loads(context_path.read_text(encoding="utf-8"))
    if mutation == "wrong_split":
        case["split"] = "test"
        _write(case_path, case)
    elif mutation == "wrong_context_id":
        context["case_id"] = "wrong_case"
        _write(context_path, context)
    elif mutation == "missing_checkpoint":
        context_path.rename(context_path.with_name("train_case_001.other.context.json"))
    elif mutation == "unknown_json":
        _write(corpus_root / "train" / "stray.json", {})
    elif mutation == "malformed_json":
        case_path.write_text("{bad", encoding="utf-8")
    elif mutation == "invalid_case":
        case["unexpected"] = True
        _write(case_path, case)
    elif mutation == "duplicate_id":
        other = corpus_root / "test" / "test_case_001.json"
        duplicate = json.loads(other.read_text(encoding="utf-8"))
        duplicate["case_id"] = "train_case_001"
        _write(other, duplicate)
    elif mutation == "missing_family":
        _write(corpus_root / "families.json", {"train_case_001": "family_a"})
    elif mutation == "normalized_duplicate":
        other = corpus_root / "test" / "test_case_001.json"
        duplicate = json.loads(other.read_text(encoding="utf-8"))
        duplicate["objective"] = "  CHECK   alpha.  "
        _write(other, duplicate)
    with pytest.raises(ValueError, match=message):
        load_corpus(corpus_root)


def test_manifest_is_deterministic_and_rejects_drift(corpus_root: Path) -> None:
    cases = load_corpus(corpus_root)
    manifest = build_manifest(cases)
    assert manifest == build_manifest(tuple(reversed(cases)))
    validate_manifest(cases, manifest)
    with pytest.raises(ValueError, match="manifest"):
        validate_manifest(cases, {"cases": []})
