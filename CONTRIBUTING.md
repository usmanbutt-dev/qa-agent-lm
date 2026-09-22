# Contribution and Git Workflow

## Branches

- `main` must remain releasable.
- Create short-lived branches named `feature/<scope>`, `fix/<scope>`, `test/<scope>`, `data/<scope>`, `train/<scope>`, or `docs/<scope>`.
- Open a pull request for every non-trivial change.
- Prefer squash merges after required checks pass.

## Commits

Use Conventional Commit prefixes:

- `feat:` product or agent capability
- `fix:` defect correction
- `test:` deterministic or evaluation coverage
- `data:` dataset or schema change
- `train:` training configuration or pipeline
- `eval:` benchmark or analysis change
- `docs:` documentation only
- `chore:` repository maintenance

Each commit should contain one coherent change and its directly related verification.

## Pull requests

Every pull request should state:

- Problem being solved.
- Scope and explicit non-goals.
- Evidence or tests performed.
- Dataset, prompt, model, or metric impact.
- Security and privacy impact where applicable.

## Data and model artifacts

- Do not commit raw datasets, secrets, checkpoints, or generated traces to normal Git history.
- Every dataset release needs provenance, license information, schema version, and a content hash.
- Every adapter release needs its base-model identifier, training configuration, dataset version, and evaluation result.
- Changing a frozen test set requires a documented reason and a new benchmark version.

## Definition of done

A change is complete when its acceptance criteria pass, deterministic behavior is covered by tests, documentation matches behavior, and generated artifacts are reproducible from committed configuration.

Run the local quality gates before opening a pull request:

```powershell
uv sync --locked --dev
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```
