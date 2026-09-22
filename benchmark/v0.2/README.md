# Initial browser benchmark corpus

This v0.2 engineering corpus has 30 cases: 10 each in `train`, `development`, and `test`. Each split has two pass, defect, recovery, ambiguity, and safety-handoff cases. Cases contain one next-decision checkpoint and its model-facing context sidecar. Three cases (`train_pass_demo`, `development_defect_demo`, and `test_safety_demo`) are intended for local-demo scripted trajectory tests; the other 27 are *illustrative decision snapshots*, not runnable webpages. Their role/name pairs are synthetic fixture observations and must not be represented as captured browser evidence.

`families.json` records the workflow family of each case. No family crosses a split. Keep development and test objectives, contexts, and oracle labels out of few-shot prompts and training data. A future model benchmark should also expand runnable application families; this initial corpus does not meet the final evaluation-plan sample sizes.

Regenerate `manifest.json` after changing case files or contexts:

```console
uv run python scripts/validate_benchmark.py --write-manifest
uv run python scripts/validate_benchmark.py
```

Manual held-out review (2026-09-22): inspected all ten test cases: receipt download, help-article navigation, notification setting persistence, audit-log pagination, analytics tab recovery, ticket attachment correction, unspecified currency, ambiguous user name, shared-data deletion, and bulk campaign send. Each has a different page/action pattern and goal from the train cases. This is a human semantic check, not proof against all near-duplicates. The loader additionally rejects exact/normalized objective duplicates and families shared across splits.
