"""Validate browser-tool schemas and their positive/negative contract cases."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts" / "v0.1"
CASES_PATH = ROOT / "tests" / "contracts" / "cases.json"


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
    request_schema = load_json(CONTRACTS / "browser-tool-request.schema.json")
    response_schema = load_json(CONTRACTS / "browser-tool-response.schema.json")
    cases = load_json(CASES_PATH)

    Draft202012Validator.check_schema(request_schema)
    Draft202012Validator.check_schema(response_schema)

    request_validator = Draft202012Validator(request_schema, format_checker=FormatChecker())
    response_validator = Draft202012Validator(response_schema, format_checker=FormatChecker())

    failures = validate_cases(
        request_validator,
        cases["valid_requests"],
        cases["invalid_requests"],
        "request",
    )
    failures.extend(
        validate_cases(
            response_validator,
            cases["valid_responses"],
            cases["invalid_responses"],
            "response",
        )
    )

    if failures:
        print("Contract validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    total_valid = len(cases["valid_requests"]) + len(cases["valid_responses"])
    total_invalid = len(cases["invalid_requests"]) + len(cases["invalid_responses"])
    print(f"Contract validation passed: {total_valid} valid and {total_invalid} invalid cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
