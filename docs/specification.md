# Project Specification

## Problem

Browser-testing agents can translate natural-language objectives into useful testing workflows, but their decisions are non-deterministic. They may choose the wrong tool, target the wrong element, repeat actions, stop too early, or continue when human judgment is required.

QA-AgentLM will test whether supervised parameter-efficient fine-tuning can improve those decisions for a narrowly defined browser-testing environment.

## Primary user

A developer or QA engineer who wants evidence-backed assistance testing a web application from a written objective.

## Core workflow

1. The user supplies a testing objective and target application.
2. The system presents a structured test plan for approval.
3. The agent observes a constrained representation of the browser state.
4. The model selects one allowed tool using a validated structured output.
5. The tool executes and returns observable evidence.
6. The loop continues until the objective passes, fails, reaches a stopping limit, or requires human help.
7. The system produces an evidence-backed result containing actions, screenshots, browser errors, timing, and model usage.

## Initial tool boundary

The first benchmark will expose only these conceptual operations:

- Navigate to an allowed URL.
- Inspect visible interactive elements.
- Click an identified element.
- Enter text into an identified field.
- Read console and network errors.
- Capture a screenshot.
- Finish with a pass or fail result.
- Request human help.

The versioned request, response, operation, and error definitions are specified in the [browser tool contract](../contracts/v0.1/README.md) and enforced by JSON Schema validation cases.

## Safety boundary

- Restrict navigation to configured local or test origins.
- Prevent arbitrary shell and filesystem access from the agent.
- Redact credentials and configured sensitive values from traces.
- Enforce maximum steps, wall-clock timeout, and retry limits.
- Require human approval before any external write, including GitHub issue creation.
- Treat webpage content as untrusted input and test prompt-injection resistance.

## Functional requirements

- Accept a plain-language testing objective.
- Produce schema-valid tool calls.
- Execute tool calls through one controlled browser interface.
- Record observations, actions, outcomes, latency, and model usage.
- Stop deterministically at configured limits.
- Preserve artifacts required to reproduce a reported failure.
- Run the same benchmark against multiple model configurations.

## Non-functional requirements

- Reproducible setup from a clean checkout.
- Typed boundaries between the agent and tools.
- Unit tests for deterministic logic and integration tests for browser tools.
- Versioned prompts, datasets, configurations, and evaluation results.
- No large datasets, checkpoints, secrets, or raw traces in normal Git history.
- Local-first operation; hosted inference and deployment are optional.

## Initial scope

- One intentionally instrumented demonstration web application.
- Five to eight browser tools.
- At least 20 held-out end-to-end testing workflows.
- One small open-weight instruction model suitable for parameter-efficient tuning.
- Zero-shot, few-shot, and fine-tuned comparisons.
- One stronger external model as an optional performance ceiling.

## Out of scope for the first release

- General-purpose autonomous browsing.
- Automatic production deployments.
- Automatic creation of external issues without approval.
- Multi-agent orchestration.
- Long-term conversational memory.
- Full-parameter model training.
- Fine-tuning to memorize application documentation.

## Acceptance criteria for `v1.0`

- A clean machine can reproduce the documented benchmark.
- Held-out workflows are isolated from training trajectories.
- All compared systems run against the same tool contracts and tasks.
- The report includes task completion, tool selection, structured-output validity, latency, and cost or compute usage.
- Claims in the README match generated evaluation artifacts.
- A short demonstration shows a successful run, a detected defect, and a safe human handoff.
- Limitations and unsuccessful experiments are documented.

## Open decisions

- Base model and tokenizer.
- Local GPU, hosted notebook, or rented training environment.
- Agent orchestration library versus a small custom loop.
- Dataset storage and versioning mechanism.
- Experiment tracking system.
- Frontend and API framework.

These decisions must follow small evidence-gathering prototypes; they are intentionally not fixed in Phase 0.
