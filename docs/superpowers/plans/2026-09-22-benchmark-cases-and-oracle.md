# Benchmark Cases and Oracle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a versioned 30-case browser benchmark, deterministic decision oracle, and three executable scripted workflows without integrating a model.

**Architecture:** JSON case files and context sidecars are loaded through one validating corpus module. A pure oracle scores structured decisions against explicit checkpoint IDs and observed targets. A small scripted workflow harness reuses the existing demo server and `BrowserSession`, then verifies terminal outcomes and cleanup. A generated manifest records sorted paths and content hashes.

**Tech Stack:** Python 3.11, JSON Schema Draft 2020-12, `jsonschema`, Playwright, pytest, Ruff, mypy, uv.

**Spec:** [Benchmark design](../specs/2026-09-22-benchmark-cases-and-oracle-design.md)

## Global Constraints

- Use the existing immutable v0.1 and v0.2 schemas; do not silently change their meanings.
- No model API, prompt, training code, baseline result, or live credentials in this issue.
- At least 30 cases: at least 10 per split and five per behavior category.
- Split by workflow family; development/test cases are never supplied as demonstrations.
- At least one executable scripted pass, fail, and human-help workflow.
- Preserve the existing `lint-type-test` CI gate and local `uv` workflow.

## Review Focus

- A context sidecar whose `case_id` or checkpoint filename disagrees with its case must fail corpus loading.
- Two cases with the same workflow family in different splits must fail corpus validation.
- A predicted `element_ref` from an old or absent observation must fail target scoring, even if its suffix resembles the right element.
- A nested `input_contains` expectation must compare object structure, not serialized substrings.
- Timeout or exception during a scripted trajectory must still close the browser session and demo server.

## File map

- `src/qa_agent_lm/benchmark/corpus.py`: schema-validating loader, split checks, manifest generation and verification.
- `src/qa_agent_lm/benchmark/oracle.py`: pure decision and terminal scorers, typed results.
- `src/qa_agent_lm/benchmark/scripted.py`: deterministic demo workflow runner; no model adapter.
- `benchmark/v0.2/{train,development,test}/`: case JSON and `.context.json` checkpoint sidecars.
- `benchmark/v0.2/families.json`: non-model-facing mapping from case IDs to workflow families.
- `benchmark/v0.2/manifest.json`: generated sorted hashes and metadata.
- `scripts/validate_benchmark.py`: CLI to validate corpus and compare regenerated manifest.
- `tests/benchmark/`: loader, oracle, and scripted integration tests.
- `README.md` and `docs/evaluation-plan.md`: benchmark reproduction and honest initial-vs-final targets.

---

### Task 1: Validated corpus and manifest

**Files:**
- Create: `src/qa_agent_lm/benchmark/__init__.py`
- Create: `src/qa_agent_lm/benchmark/corpus.py`
- Create: `scripts/validate_benchmark.py`
- Test: `tests/benchmark/test_corpus.py`

**Interfaces:**
- Consumes: `contracts/v0.2/benchmark-case.schema.json`, `agent-context.schema.json`.
- Produces: `load_corpus(root: Path) -> tuple[BenchmarkCase, ...]`, `build_manifest(cases: tuple[BenchmarkCase, ...]) -> dict[str, object]`, `validate_manifest(cases: tuple[BenchmarkCase, ...], manifest: Mapping[str, object]) -> None`.
- `BenchmarkCase` stores `case_id`, `split`, `family`, `data: dict[str, object]`, sorted checkpoint contexts, and relative content hashes. Raise `ValueError` with file/case context for invalid corpus data.

- [ ] **Step 1: Write failing loader tests.** Use a temporary corpus with one schema-valid case and matching sidecar. Assert sorted load order, case/context ID match, and exact SHA-256 of file bytes. Parameterize duplicate IDs, duplicate content hashes, wrong split directory, unknown JSON files, malformed JSON, schema-invalid fields, sidecar checkpoint mismatch, family split conflicts, and normalized-objective duplicates across splits. Include a sidecar case-ID mismatch test.

```python
def test_rejects_cross_split_family(valid_corpus: Path) -> None:
    families = valid_corpus / "families.json"
    mapping = json.loads(families.read_text(encoding="utf-8"))
    mapping["test_case_001"] = mapping["train_case_001"]
    families.write_text(json.dumps(mapping), encoding="utf-8")
    with pytest.raises(ValueError, match="workflow family"):
        load_corpus(valid_corpus)
```

- [ ] **Step 2: Run `uv run pytest tests/benchmark/test_corpus.py -q`.** Expect import or assertion failures before implementation.
- [ ] **Step 3: Implement the smallest loader.** Read `families.json` as a complete `{case_id: family_id}` map with no unknown or missing IDs. Load local schemas from repo paths, register immutable v0.1 request schema for references, validate cases and contexts, and map `<case_id>.<checkpoint_id>.context.json` sidecars to their case/checkpoint. Enforce sorted order and split/family rules and hash raw UTF-8 bytes. Normalize objectives with Unicode NFKC, case folding, and collapsed whitespace. Do not use network schema resolution.

```python
def normalized_objective(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
```

- [ ] **Step 4: Implement canonical manifest build/validation and CLI.** Serialize with `sort_keys=True`, two-space indentation, LF newline, sorted case IDs and sidecars. CLI reads `benchmark/v0.2/manifest.json`, compares to regenerated structure, and exits nonzero on drift. Add tests proving byte-for-byte stable generation and drift detection.

```python
expected = json.dumps(build_manifest(cases), indent=2, sort_keys=True) + "\n"
if manifest_path.read_text(encoding="utf-8") != expected:
    raise ValueError("benchmark manifest is stale")
```
- [ ] **Step 5: Run `uv run pytest tests/benchmark/test_corpus.py -q`, `uv run ruff check .`, and `uv run mypy`.** Fix only failures from this task.
- [ ] **Step 6: Commit:** `git add src/qa_agent_lm/benchmark scripts/validate_benchmark.py tests/benchmark/test_corpus.py && git commit -m "feat: validate benchmark corpus"`.

### Task 2: Pure decision and terminal oracle

**Files:**
- Create: `src/qa_agent_lm/benchmark/oracle.py`
- Test: `tests/benchmark/test_oracle.py`

**Interfaces:**
- Consumes: `BenchmarkCase` and checkpoint context from Task 1; v0.2 decision schema.
- Produces: `score_decision(case: BenchmarkCase, checkpoint_id: str, prediction: object) -> DecisionScore` and `score_terminal(case: BenchmarkCase, prediction: object) -> TerminalScore`.
- `DecisionScore` includes `schema_valid`, `tool_correct`, `target_correct: bool | None`, `input_correct`, and stable reason codes. `TerminalScore` includes `schema_valid`, `terminal_correct`, and reason codes.

- [ ] **Step 1: Write table-driven failing tests.** Cover alternative acceptable operations; wrong operation; correct role/name through current `element_ref`; stale/unknown refs; wrong target; schema-invalid decision; nested `input_contains` match/mismatch; unknown checkpoint; finish pass/fail mismatch; human-help reason mismatch. Assert deterministic result values and reasons.

```python
@pytest.mark.parametrize(
    ("prediction", "tool_correct"),
    [
        ({"contract_version": "0.2", "operation": "inspect", "input": {}}, True),
        (
            {"contract_version": "0.2", "operation": "click", "input": {"element_ref": "el_1"}},
            False,
        ),
    ],
)
def test_tool_selection(
    case_with_inspect_checkpoint: BenchmarkCase, prediction: dict[str, object], tool_correct: bool
) -> None:
    score = score_decision(case_with_inspect_checkpoint, "observe", prediction)
    assert score.tool_correct is tool_correct
```

- [ ] **Step 2: Run `uv run pytest tests/benchmark/test_oracle.py -q`.** Expect import or assertion failures.
- [ ] **Step 3: Implement schema-first scoring.** Validate the prediction using the v0.2 decision schema and local v0.1 reference registry. Resolve targets only against the supplied observation's `elements`. Compare expected nested objects recursively by key/value containment; compare arrays by exact value unless the spec is amended. Treat missing target expectations as `target_correct=None`. Reject unknown checkpoint IDs explicitly.

```python
def contains(actual: object, expected: object) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and contains(actual[key], value) for key, value in expected.items()
        )
    return actual == expected
```

- [ ] **Step 4: Implement terminal scoring.** `finish` requires the expected outcome; `request_human_help` requires the expected reason. Schema-invalid predictions never earn terminal credit. No browser or model calls in this module.

```python
terminal_correct = (
    prediction["operation"] == expected["operation"]
    and prediction["input"]["outcome" if expected["operation"] == "finish" else "reason"]
    == expected["outcome" if expected["operation"] == "finish" else "reason"]
)
```
- [ ] **Step 5: Run focused tests, Ruff, and mypy.** Verify reason codes remain stable across repeated calls.
- [ ] **Step 6: Commit:** `git add src/qa_agent_lm/benchmark/oracle.py tests/benchmark/test_oracle.py && git commit -m "feat: score benchmark decisions"`.

### Task 3: Initial 30-case corpus

**Files:**
- Create: `benchmark/v0.2/{train,development,test}/*.json`
- Create: matching `*.context.json` decision sidecars
- Create: `benchmark/v0.2/families.json`
- Create: `benchmark/v0.2/manifest.json`
- Test: `tests/benchmark/test_dataset.py`

**Interfaces:**
- Consumes: Task 1 loader and manifest builder; Task 2 oracle.
- Produces: stable initial dataset version `v0.2`, with at least 30 unique case IDs and explicit workflow-family mapping in `families.json`. Do not modify the released v0.2 schema to add a family field.

- [ ] **Step 1: Write failing dataset assertions.** Assert at least 30 cases, at least 10 per split, at least five tags each for `pass`, `defect`, `recovery`, `ambiguity`, and `safety_handoff`, and at least one terminal each for pass, fail, and human help. Assert manifest freshness and that all sidecars load and match their checkpoint history.

```python
def test_initial_corpus_meets_minimums() -> None:
    cases = load_corpus(Path("benchmark/v0.2"))
    assert len(cases) >= 30
    for split in ("train", "development", "test"):
        assert sum(case.split == split for case in cases) >= 10
    for category in ("pass", "defect", "recovery", "ambiguity", "safety_handoff"):
        assert sum(category in case.data["tags"] for case in cases) >= 5
```

- [ ] **Step 2: Run `uv run pytest tests/benchmark/test_dataset.py -q`.** Expect failure because no corpus exists.
- [ ] **Step 3: Author cases and sidecars.** Use distinct scenario families across splits, not objective paraphrases. Keep objectives concrete and seed data nonsensitive. Include pass, defect detection, recovery after a bad action, missing-information ambiguity, and sensitive-action handoff. Use actual observed role/name pairs and operation inputs allowed by the schemas. Review held-out cases for semantic near-duplicates with train cases.

```json
{
  "contract_version": "0.2",
  "case_id": "train_pass_001",
  "title": "Staging check passes",
  "objective": "Verify the staging deployment check succeeds.",
  "split": "train",
  "tags": ["pass"],
  "setup": {"start_path": "/", "seed": {"environment": "staging"}},
  "oracle": {
    "checkpoints": [{
      "checkpoint_id": "choose_check",
      "after_operations": ["navigate", "inspect", "type"],
      "acceptable_next": [{"operation": "click", "target": {"role": "button", "name": "Run successful check"}}]
    }],
    "terminal": {"operation": "finish", "outcome": "pass"},
    "max_steps": 10
  }
}
```

- [ ] **Step 4: Generate the manifest with a deterministic command from Task 1.** Check in its output, then run the validation CLI in comparison mode.

```powershell
uv run python scripts/validate_benchmark.py --write-manifest
uv run python scripts/validate_benchmark.py
```
- [ ] **Step 5: Run dataset tests, contract validation, Ruff, and mypy.** Manually inspect ten held-out cases for leakage and record that review in `benchmark/v0.2/README.md`.
- [ ] **Step 6: Commit:** `git add benchmark/v0.2 tests/benchmark/test_dataset.py && git commit -m "data: add initial browser benchmark"`.

### Task 4: Scripted trajectory proof and CI documentation

**Files:**
- Create: `src/qa_agent_lm/benchmark/scripted.py`
- Test: `tests/benchmark/test_scripted.py`
- Modify: `README.md`, `docs/evaluation-plan.md`, `.github/workflows/ci.yml` only if the existing `uv run pytest` job does not already discover new tests.

**Interfaces:**
- Consumes: Task 1 corpus, Task 2 terminal scorer, existing `demo.app.create_server` and `BrowserSession`.
- Produces: `run_scripted_case(case: BenchmarkCase, script: Callable[[BrowserSession, str], Awaitable[ScriptedTrace]], artifact_dir: Path) -> ScriptedRunResult`; the script receives a session and demo origin, uses observed references, and returns its validated decisions and final observation/evidence in `ScriptedTrace`. The result includes terminal score, operation count, validity count, and cleanup state, excluding timing and ephemeral port from equality.

- [ ] **Step 1: Write failing integration tests.** Use a fresh demo server/session per run. Exercise one pass, one fail with diagnostics, and one human-help case. Run each twice and compare stable results. Inject a timeout and a malformed scripted decision; assert the browser and server close.

```python
@pytest.mark.asyncio
async def test_scripted_pass_is_repeatable(pass_case: BenchmarkCase, tmp_path: Path) -> None:
    first = await run_scripted_case(pass_case, run_passing_demo, tmp_path / "first")
    second = await run_scripted_case(pass_case, run_passing_demo, tmp_path / "second")
    assert first == second
    assert first.cleanup_state == "closed"
```

- [ ] **Step 2: Run `uv run pytest tests/benchmark/test_scripted.py -q`.** Expect import or assertion failures.
- [ ] **Step 3: Implement a narrow scripted runner and three scripts.** Scripts use `navigate`, `inspect`, `type`, `click`, and relevant evidence tools; each resolves live element refs by observed role/name and verifies page state or diagnostics before returning a terminal decision. The runner validates the recorded v0.2 decisions, scores the terminal result, resolves local demo origin at runtime, and uses `async with BrowserSession(...)` plus `try/finally` around server lifecycle. A script that only asserts `finish(pass)` without checking the page must fail the test. Do not build a model adapter or general agent loop.

```python
with running_demo() as origin:
    async with BrowserSession(
        BrowserSessionConfig(allowed_origins=(origin,), artifact_dir=artifact_dir)
    ) as session:
        trace = await script(session, origin)
        for decision in trace.decisions:
            validate_scripted_decision(decision)
        return score_scripted_terminal(case, trace, session.state)
```
- [ ] **Step 4: Document reproduction.** Add dataset counts, split policy, manifest command, scripted-test command, and the distinction between this engineering corpus and final evaluation targets. Do not report model performance.
- [ ] **Step 5: Run `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`, `uv run python scripts/validate_contracts.py`, `uv run python scripts/validate_benchmark.py`, and `uv run pytest`.** Confirm CI runs the same pytest suite.
- [ ] **Step 6: Commit:** `git add src/qa_agent_lm/benchmark/scripted.py tests/benchmark/test_scripted.py README.md docs/evaluation-plan.md .github/workflows/ci.yml && git commit -m "test: prove scripted benchmark workflows"`.

## Self-review against the spec

- Corpus, sidecars, stable IDs, hashes, schema validation, and family split isolation: Tasks 1 and 3.
- At least 30 cases and all behavior categories: Task 3.
- Pure decision/target/input/terminal oracle: Task 2.
- Scripted pass/fail/help and cleanup determinism: Task 4.
- No model integration, honest sample-size limits, no secret data: global constraints and Task 4 docs.
- No placeholders or undefined task dependencies remain; implementation starts only after plan review.
