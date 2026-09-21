# Evaluation Plan

## Purpose

Evaluation determines whether fine-tuning provides measurable value beyond prompting. The benchmark must exist before training begins, and the held-out labels must not influence training examples or prompt iteration.

## Compared systems

1. **Zero-shot base:** base model with tool definitions and no demonstrations.
2. **Few-shot base:** same model and tools with a small fixed set of demonstrations.
3. **Fine-tuned:** same base model with a parameter-efficient adapter.
4. **Reference model:** optional stronger model using the same tools and limits.

Every system receives identical objectives, browser states, tool schemas, stopping limits, and evaluation logic.

## Evaluation units

### Decision-level cases

Given an objective, browser state, and action history, evaluate the next action selected by the model.

### Trajectory-level cases

Run a complete browser-testing task and evaluate whether the system reaches the correct terminal outcome with acceptable actions.

### Safety cases

Present ambiguous objectives, missing credentials, prompt injection, disallowed origins, destructive requests, and exhausted step limits. Evaluate whether the system refuses, stops, or requests human help correctly.

## Dataset separation

- Split by application or workflow family, not by individual action.
- Keep test applications or flows unseen during training.
- Detect exact and near duplicates before finalizing splits.
- Freeze and hash the test set before fine-tuning.
- Never use test failures as new training data during the reported experiment.

## Primary metrics

| Metric | Definition |
|---|---|
| Tool-selection accuracy | Correct next tool divided by evaluated decisions |
| Target-selection accuracy | Correct element or destination when the tool requires one |
| Structured-output validity | Outputs accepted by the tool-call schema without repair |
| Task-completion rate | Workflows reaching the correct terminal outcome |
| Safe-handoff accuracy | Cases correctly escalated instead of guessed or executed |
| Step efficiency | Valid tool calls required per completed workflow |

## Operational metrics

- End-to-end latency per workflow.
- Model input and output tokens.
- API cost or local compute time.
- Tool-call failure and retry rate.
- Maximum memory used during inference when measured locally.

## Quality safeguards

- Report the number and origin of examples in every split.
- Preserve raw predictions for error analysis with secrets redacted.
- Use deterministic graders for schema validity, allowed actions, known targets, and terminal states.
- Use human review only where the expected result cannot be expressed deterministically.
- Record confidence intervals or repeated-run variance for non-deterministic trajectory metrics.
- Publish confusion or error categories, not only aggregate scores.

## Required baselines

Fine-tuning is justified only if it materially improves at least one primary metric without unacceptable degradation elsewhere. A prompt-only system that already meets the target is a valid negative result and should stop unnecessary training.

## Initial benchmark target

The first benchmark should include at least:

- 50 held-out decision-level examples.
- 20 held-out trajectory-level workflows.
- 10 safety and human-handoff cases.
- Two repetitions per trajectory for the initial report, increased if variance is high.

These are minimum sample sizes for engineering feedback, not claims of statistical completeness.

## Result artifact

The evaluation command must generate a machine-readable result containing:

- Git commit and dirty-worktree status.
- Model and adapter identifiers.
- Dataset version and hashes.
- Prompt and tool-schema versions.
- Runtime configuration and random seed.
- Per-case results and aggregate metrics.
- Latency, token usage, and cost or compute usage.
- Failure categories.

The public report and README must be derived from this artifact rather than manually maintained numbers.
