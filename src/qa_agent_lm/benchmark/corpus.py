"""Load, validate, and fingerprint versioned benchmark cases."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SPLITS = ("train", "development", "test")


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    split: str
    family: str
    data: dict[str, Any]
    contexts: dict[str, dict[str, Any]]
    content_hash: str
    context_hashes: dict[str, str]
    path: str


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"JSON error in {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return cast(dict[str, Any], value)


def _validator(name: str) -> Draft202012Validator:
    schema = _read_json(_REPO_ROOT / "contracts" / "v0.2" / name)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _check_schema(value: dict[str, Any], validator: Draft202012Validator, path: Path) -> None:
    errors = list(validator.iter_errors(value))
    if errors:
        raise ValueError(f"schema error in {path}: {errors[0].message}")


def _normalized_objective(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_corpus(root: Path) -> tuple[BenchmarkCase, ...]:
    """Load all cases, rejecting malformed or split-leaking data."""
    families = _read_json(root / "families.json")
    if not all(
        isinstance(key, str) and isinstance(value, str) and value for key, value in families.items()
    ):
        raise ValueError("families must map case IDs to nonempty family IDs")
    case_validator = _validator("benchmark-case.schema.json")
    context_validator = _validator("agent-context.schema.json")
    cases: list[BenchmarkCase] = []
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    family_splits: dict[str, str] = {}
    objectives: dict[str, str] = {}
    for split in _SPLITS:
        split_dir = root / split
        if not split_dir.is_dir():
            continue
        for path in sorted(split_dir.glob("*.json")):
            if path.name.endswith(".context.json"):
                continue
            if path.stem not in families:
                candidate = _read_json(path)
                if case_validator.is_valid(candidate):
                    raise ValueError(f"families mapping missing case_id: {path.stem}")
                raise ValueError(f"unknown JSON case file: {path}")
            data = _read_json(path)
            _check_schema(data, case_validator, path)
            case_id = cast(str, data["case_id"])
            if path.name != f"{case_id}.json":
                raise ValueError(f"case_id filename mismatch: {path}")
            if data["split"] != split:
                raise ValueError(f"split directory mismatch: {path}")
            if case_id in seen_ids:
                raise ValueError(f"duplicate case_id: {case_id}")
            seen_ids.add(case_id)
            content_hash = _sha256(path)
            if content_hash in seen_hashes:
                raise ValueError(f"duplicate case content hash: {path}")
            seen_hashes.add(content_hash)
            if case_id not in families:
                raise ValueError(f"families mapping missing case_id: {case_id}")
            family = cast(str, families[case_id])
            previous_split = family_splits.setdefault(family, split)
            if previous_split != split:
                raise ValueError(f"workflow family {family} spans splits")
            objective = _normalized_objective(cast(str, data["objective"]))
            previous_case = objectives.setdefault(objective, case_id)
            if previous_case != case_id:
                raise ValueError(f"normalized objective duplicate: {case_id} and {previous_case}")
            contexts: dict[str, dict[str, Any]] = {}
            context_hashes: dict[str, str] = {}
            checkpoints = {
                cast(str, checkpoint["checkpoint_id"]): checkpoint
                for checkpoint in data["oracle"]["checkpoints"]
            }
            for checkpoint_id, checkpoint in checkpoints.items():
                context_path = split_dir / f"{case_id}.{checkpoint_id}.context.json"
                if not context_path.is_file():
                    raise ValueError(f"missing checkpoint context: {context_path}")
                context = _read_json(context_path)
                _check_schema(context, context_validator, context_path)
                if context["case_id"] != case_id:
                    raise ValueError(f"context case_id mismatch: {context_path}")
                if context["objective"] != data["objective"]:
                    raise ValueError(f"context objective mismatch: {context_path}")
                operations = [item["operation"] for item in context["history"]]
                if operations != checkpoint["after_operations"]:
                    raise ValueError(f"checkpoint history mismatch: {context_path}")
                contexts[checkpoint_id] = context
                context_hashes[checkpoint_id] = _sha256(context_path)
            cases.append(
                BenchmarkCase(
                    case_id=case_id,
                    split=split,
                    family=family,
                    data=data,
                    contexts=dict(sorted(contexts.items())),
                    content_hash=content_hash,
                    context_hashes=dict(sorted(context_hashes.items())),
                    path=path.relative_to(root).as_posix(),
                )
            )
    if set(families) != seen_ids:
        raise ValueError("families mapping has unknown case_id values")
    known = {"families.json", "manifest.json"}
    known.update(case.path for case in cases)
    for case in cases:
        known.update(
            f"{case.split}/{case.case_id}.{checkpoint_id}.context.json"
            for checkpoint_id in case.contexts
        )
    extras = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.json")
        if path.relative_to(root).as_posix() not in known
    )
    if extras:
        raise ValueError(f"unknown JSON files: {extras}")
    return tuple(sorted(cases, key=lambda case: case.case_id))


def build_manifest(cases: tuple[BenchmarkCase, ...]) -> dict[str, object]:
    """Create reproducible metadata without loading any model-facing data."""
    return {
        "version": "0.2",
        "cases": [
            {
                "case_id": case.case_id,
                "path": case.path,
                "split": case.split,
                "family": case.family,
                "sha256": case.content_hash,
                "contexts": [
                    {
                        "checkpoint_id": checkpoint_id,
                        "path": f"{case.split}/{case.case_id}.{checkpoint_id}.context.json",
                        "sha256": content_hash,
                    }
                    for checkpoint_id, content_hash in case.context_hashes.items()
                ],
            }
            for case in sorted(cases, key=lambda case: case.case_id)
        ],
    }


def validate_manifest(cases: tuple[BenchmarkCase, ...], manifest: Mapping[str, object]) -> None:
    if manifest != build_manifest(cases):
        raise ValueError("benchmark manifest is stale")
