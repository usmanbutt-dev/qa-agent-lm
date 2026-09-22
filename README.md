# QA-AgentLM

QA-AgentLM is a research-backed portfolio project investigating whether parameter-efficient fine-tuning improves the reliability and efficiency of an LLM-based browser-testing agent.

The planned system will translate a testing objective into browser actions, execute those actions through a constrained Playwright tool layer, collect evidence, and stop or request human help when the task becomes ambiguous or unsafe.

## Research question

> Does parameter-efficient fine-tuning improve browser-tool selection and end-to-end task completion compared with zero-shot and few-shot prompting?

## Current status

**Phase 0: specification and evaluation design.** No model, framework, or dataset has been selected yet.

## Development

Requirements: Python 3.11 and [uv](https://docs.astral.sh/uv/).

```powershell
uv sync --locked --dev
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

These are the same quality gates run by CI. Update `uv.lock` intentionally with `uv lock` whenever project dependencies change.

## Project principles

- Establish evaluation before training.
- Compare against prompt-only baselines.
- Prefer one constrained agent over unnecessary multi-agent complexity.
- Treat browser state and tool output as ground truth.
- Require human approval for consequential external actions.
- Publish measured results, including negative results.
- Keep training, evaluation, and application code reproducible.

## Documents

- [Project specification](docs/specification.md)
- [Evaluation plan](docs/evaluation-plan.md)
- [Browser tool contract v0.1](contracts/v0.1/README.md)
- [Contribution and Git workflow](CONTRIBUTING.md)

## Planned milestones

| Version | Deliverable |
|---|---|
| `v0.1` | Deterministic Playwright tool layer |
| `v0.2` | Prompt-only baseline agent |
| `v0.3` | Reproducible evaluation benchmark |
| `v0.4` | Validated training dataset |
| `v0.5` | Parameter-efficient fine-tuned model |
| `v0.6` | Comparative evaluation report |
| `v1.0` | Portfolio application and documented release |

## License

No license has been selected. Until one is added, the repository is not licensed for redistribution or reuse.
