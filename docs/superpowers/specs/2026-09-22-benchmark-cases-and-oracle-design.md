# Benchmark Cases and Oracle Design

## Purpose and scope

Issue #14 supplies a reproducible benchmark for the browser-testing agent before any model baseline or fine-tuning run. It must measure next-decision quality and a small number of complete browser workflows without relying on subjective grading. The first corpus contains at least 30 cases spanning pass, defect, recovery, ambiguity, and safety handoff. This is an engineering benchmark, not yet the final evaluation-plan target of 50 held-out decisions, 20 held-out trajectories, and 10 safety cases.

The corpus and scorer are provider-neutral. They use the v0.2 agent-context, agent-decision, and benchmark-case contracts, and the v0.1 browser operations. No model API, prompt, training code, or baseline result is part of this issue.

## Corpus and split policy

Cases are checked-in JSON, one case per file, under `benchmark/v0.2/{train,development,test}/`. Every file has a stable `case_id` and passes the v0.2 benchmark-case schema. Decision checkpoints have a separate `*.context.json` sidecar validated by the v0.2 agent-context schema; its `case_id` must match the case file, and its filename identifies the checkpoint. A manifest lists each case ID, case path, sidecar paths, split, workflow family, and SHA-256 hashes. The manifest is generated and validated, not maintained as a second source of truth.

The minimum initial corpus is 30 cases: at least 10 train, 10 development, and 10 test; at least five cases in each of the five behavior categories. Cases may carry multiple category tags. At least one runnable end-to-end workflow per terminal category—pass, fail, and human help—uses the local demo application. The rest may be decision checkpoints. This mix keeps the first deliverable tractable while exercising both scoring levels.

Splits are assigned by workflow family, not by changing a label on otherwise identical cases. One workflow family belongs to exactly one split. A family is the underlying scenario and page/action pattern, not the wording of its objective. Case IDs and case hashes must be unique. An exact-duplicate and normalized-objective check prevents accidental reuse across splits; semantic near-duplicate review is documented as a manual release check. Development and test cases must never be used as few-shot demonstrations or later supervised training rows. Test labels remain in the repository for deterministic grading but are excluded from model prompts and runtime traces.

No credentials, tokens, passwords, or personal data appear in case files or seed values. Seed values are nonsensitive fixture parameters. The benchmark loader rejects unknown files, malformed cases, duplicate IDs, split/family conflicts, and manifest drift before running any evaluation.

## Decision cases

Each decision sidecar provides a reproducible context: objective, browser observation, action-history summary, available operations, and remaining limits. Its filename identifies the applicable oracle checkpoint in the case file. Model-facing context contains no oracle fields, split label, expected operation, or terminal outcome. Sidecars are immutable snapshots, not regenerated from a live page during decision-level scoring.

The existing `benchmark-case.schema.json` supplies setup, checkpoints, acceptable next decisions, and terminal expectation. Checkpoints are matched by explicit checkpoint ID in the evaluator, not guessed from the operation history alone: two states can have identical operation names but different observations. `after_operations` remains a documented sanity check for the supplied history. The scorer treats any `acceptable_next` entry as correct, so legitimate alternative actions are not penalized.

For a predicted decision, the oracle first validates the v0.2 decision schema. Invalid JSON or schema-invalid decisions receive `schema_valid=false`; downstream tool and target metrics are not scored as correct. A schema-valid decision receives tool-selection credit if its operation matches any acceptable next decision. Target-selection credit requires the selected element reference to resolve to the observed element whose role and accessible name match an acceptable target; raw selectors and unknown/stale references fail. `input_contains` checks required input fields by structural containment, not by substring matching. Unspecified extra input fields remain subject to the operation schema. The scorer returns a typed per-case result with explicit reasons, not only a Boolean.

## Trajectory cases

Runnable workflows start the local demo server from a clean state and create a new restricted `BrowserSession` per case. Setup uses only configured local origins and the case's `start_path` and nonsensitive seed. The evaluator passes the objective and observations to the future agent loop, then checks the final operation and pass/fail outcome or human-help reason against the oracle. It also records steps and contract-validity counts. The browser session is closed on success, error, timeout, and human handoff.

Issue #14 does not implement the provider-neutral agent loop from Issue #15. Its trajectory tests use a deterministic scripted decision source to prove that the demo cases and oracle are executable. Baseline model runs wait for Issues #15–#17.

## Determinism and test strategy

The loader sorts case paths and emits results in case-ID order. No random case generation occurs at evaluation time. Server state is reset for each trajectory; tests run with fixed fixture values and explicit timeouts. Case hashes change whenever case contents change. The scorer has table-driven tests for acceptable alternatives, wrong operation, wrong target, invalid decision, nested `input_contains`, terminal mismatch, and unknown checkpoint.

Corpus validation tests assert counts, required categories, unique IDs, family-level split isolation, schema validity, stable manifest generation, and no exact or normalized-objective duplicates across splits. Integration tests run scripted pass, fail, and human-help trajectories twice and compare stable results, excluding volatile timing and ephemeral port values. CI runs corpus validation and the tests through the existing `lint-type-test` gate.

## Boundaries and limitations

- Case IDs are stable; case content is versioned by hash. Changing a held-out case after baseline publication requires a new dataset version and invalidates earlier comparisons.
- Decision scoring can verify structured choices, not whether a model's private reasoning was sound.
- The initial runnable trajectory set is deliberately small. It does not satisfy the larger sample-size target in `docs/evaluation-plan.md` or justify claims of statistically reliable improvement.
- The demo app is the first benchmark environment. Adding a second application family is expected before the final held-out trajectory benchmark.
- Timing and token/cost accounting belong to the agent-loop and baseline issues, not this oracle.
