# Agent and Benchmark Contracts v0.2

These schemas define the provider-neutral boundary used to evaluate model decisions before fine-tuning.

## Files

- `agent-context.schema.json` is the complete bounded input given to a model for one decision.
- `agent-decision.schema.json` permits exactly one browser operation and reuses the immutable v0.1 operation-input definitions.
- `benchmark-case.schema.json` defines deterministic setup, data split, oracle checkpoints, acceptable next decisions, and terminal outcome.

Transport-owned request and session identifiers are intentionally absent from model output. The runtime adds them after validating a decision. Free-form chain-of-thought is also absent; evaluation concerns observable decisions, not hidden reasoning.

## Secret handling

Contracts contain no credential or secret field. Benchmark seed data may contain only scalar, non-sensitive fixture values. Runtime credentials must be resolved from local configuration after model output validation and must never be placed in prompts, cases, traces, or Git.

## Dataset isolation

`train` cases may be used for demonstrations and future supervised training. `development` cases may guide engineering decisions but not training. `test` cases remain held out until a frozen evaluation run. Moving a case between splits requires a new dataset version and invalidates comparisons with earlier results.

## Versioning

The v0.2 schemas are immutable after release. Structural or semantic changes require another versioned contract directory. They reference v0.1 browser input definitions by immutable schema identifier.
