"""Validate all versioned schemas and their positive/negative contract cases."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
V01_CONTRACTS = ROOT / "contracts" / "v0.1"
V02_CONTRACTS = ROOT / "contracts" / "v0.2"
V01_CASES_PATH = ROOT / "tests" / "contracts" / "cases.json"
V02_CASES_PATH = ROOT / "tests" / "contracts" / "agent-benchmark-cases.json"


def load_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def validate_cases(
    validator: Draft202012Validator,
    valid_cases: list[dict[str, Any]],
    invalid_cases: list[dict[str, Any]],
    label: str,
) -> list[str]:
    failures: list[str] = []

    for index, case in enumerate(valid_cases, start=1):
        errors = sorted(validator.iter_errors(case), key=lambda error: list(error.path))
        if errors:
            failures.append(f"{label} valid case {index} failed: {errors[0].message}")

    for case in invalid_cases:
        if validator.is_valid(case["value"]):
            failures.append(f"{label} invalid case passed: {case['name']}")

    return failures


def main() -> int:
    browser_request = load_json(V01_CONTRACTS / "browser-tool-request.schema.json")
    schemas = {
        "browser request": browser_request,
        "browser response": load_json(V01_CONTRACTS / "browser-tool-response.schema.json"),
        "agent context": load_json(V02_CONTRACTS / "agent-context.schema.json"),
        "agent decision": load_json(V02_CONTRACTS / "agent-decision.schema.json"),
        "benchmark case": load_json(V02_CONTRACTS / "benchmark-case.schema.json"),
    }
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)

    registry = Registry().with_resource(
        str(browser_request["$id"]), Resource.from_contents(browser_request)
    )
    validators = {
        name: Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
            registry=registry,
        )
        for name, schema in schemas.items()
    }
    v01_cases = load_json(V01_CASES_PATH)
    v02_cases = load_json(V02_CASES_PATH)
    groups = (
        ("browser request", v01_cases["valid_requests"], v01_cases["invalid_requests"]),
        (
            "browser response",
            v01_cases["valid_responses"],
            v01_cases["invalid_responses"],
        ),
        ("agent context", v02_cases["valid_contexts"], v02_cases["invalid_contexts"]),
        ("agent decision", v02_cases["valid_decisions"], v02_cases["invalid_decisions"]),
        (
            "benchmark case",
            v02_cases["valid_benchmark_cases"],
            v02_cases["invalid_benchmark_cases"],
        ),
    )
    failures: list[str] = []
    for label, valid_cases, invalid_cases in groups:
        failures.extend(validate_cases(validators[label], valid_cases, invalid_cases, label))

    if failures:
        print("Contract validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    total_valid = sum(len(valid_cases) for _, valid_cases, _ in groups)
    total_invalid = sum(len(invalid_cases) for _, _, invalid_cases in groups)
    print(f"Contract validation passed: {total_valid} valid and {total_invalid} invalid cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
