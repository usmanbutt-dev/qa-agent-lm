# Browser Tool Contract v0.1

This directory is the language- and model-provider-neutral contract between the future agent runtime and deterministic browser layer.

## Envelopes

Every request contains:

- `contract_version`: exactly `0.1`.
- `request_id`: caller-generated correlation identifier.
- `session_id`: controlled browser-session identifier.
- `operation`: one of the eight allowed operations.
- `input`: operation-specific arguments.

Every response echoes the version, request identifier, and operation. A successful response contains `result`; a failed response contains `error`. It must never contain both.

## Operations

| Operation | Purpose | Key safety property |
|---|---|---|
| `navigate` | Visit a URL | Runtime must enforce the configured origin allowlist. |
| `inspect` | Return bounded visible interactive elements | Produces stable `el_...` references; raw DOM is not exposed. |
| `click` | Activate an observed element | Accepts an element reference, not CSS or XPath. |
| `type` | Enter text into an observed field | Input length is bounded; trace redaction is a runtime responsibility. |
| `read_diagnostics` | Read bounded console or network failures | Result size is bounded and may be marked truncated. |
| `take_screenshot` | Save visual evidence | Returns an opaque artifact identifier, not a filesystem path. |
| `finish` | End with `pass` or `fail` | Requires a summary and explicit evidence list. |
| `request_human_help` | Pause for user judgment | Makes ambiguity and sensitive actions explicit terminal states. |

Element references are scoped to the latest observation. Implementations must reject expired references with `STALE_ELEMENT_REFERENCE`.

## Error catalog

Retryability is normative. Implementations must return the value in this table for the corresponding code.

| Code | Retryable | Meaning |
|---|---:|---|
| `INVALID_REQUEST` | No | Request failed contract or runtime validation. |
| `SESSION_NOT_FOUND` | No | Session identifier is unknown. |
| `SESSION_CLOSED` | No | Session has already reached a terminal state. |
| `ORIGIN_NOT_ALLOWED` | No | Navigation target is outside the configured boundary. |
| `TARGET_NOT_FOUND` | Yes | Referenced target is not currently available; inspect again. |
| `STALE_ELEMENT_REFERENCE` | Yes | Reference belongs to an older observation; inspect again. |
| `NAVIGATION_TIMEOUT` | Yes | Navigation exceeded its operation timeout. |
| `ACTION_TIMEOUT` | Yes | Non-navigation action exceeded its operation timeout. |
| `STEP_LIMIT_EXCEEDED` | No | Session exhausted its action budget. |
| `WALL_CLOCK_TIMEOUT` | No | Session exhausted its total time budget. |
| `DOWNLOAD_BLOCKED` | No | Page attempted a disallowed download. |
| `EXTERNAL_PROTOCOL_BLOCKED` | No | Page attempted a non-HTTP(S) external protocol. |
| `ARTIFACT_LIMIT_EXCEEDED` | No | Artifact count or size budget was exhausted. |
| `TOOL_EXECUTION_FAILED` | No | Tool failed without a safer, more specific code. |

## Versioning

Schemas are immutable after release. Backward-compatible clarifications update documentation only. Any structural or semantic schema change requires a new contract directory and `contract_version`.

## Validation

Run the pinned standalone validator:

```powershell
uv run --script scripts/validate_contracts.py
```

It checks both schemas against Draft 2020-12, asserts that all valid fixtures pass, and asserts that all invalid fixtures fail.
