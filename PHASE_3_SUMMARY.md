# Phase 3 Summary

## What was done
- Implemented per-incident state scoping in `target_system/stub_metrics.py` and `target_system/state.json`: restructured `state.json` as a dictionary keyed by `incident_id`, updated `read_state(incident_id)` to auto-initialize a fresh `BASELINE_DEGRADED_STATE` for uninitialized incidents, and updated `write_state(incident_id, new_state)` to mutate only that incident's entry.
- Created `sandbox/Dockerfile` and updated `sandbox/execute_action.py` to accept `INCIDENT_ID` env var and mutate only that incident's entry inside mounted `/data/state.json`.
- Extended `sandbox/executor.py` to pass `INCIDENT_ID` into containers and fallback host executions.
- Built Verifier Agent in `agents/verifier.py` calling Groq `openai/gpt-oss-20b` with Structured Outputs (`strict: True`), non-streaming, 1 retry backoff, and a deterministic local sanity check safety net that overrides invalid LLM verdicts when degraded metrics persist.
- Built Communicator Agent in `agents/communicator.py` calling Groq `openai/gpt-oss-20b` for plain text completions with 1 retry backoff to generate concise postmortem summaries from incident event logs.
- Extended Orchestrator in `orchestrator/main.py` to drive the complete closed-loop pipeline (`remediating` -> `verifying` -> `communicating` -> `done`/`failed`), snapshot pre/post metrics, store postmortems on `IncidentState`, pass `incident_id` to sandbox executor, and handle Policy Gateway / Docker connection errors cleanly.
- Added `target_system/state.json` to `.gitignore`.
- Extended `demo_scripts/test_phase3.py` with 8 test cases verifying full pipeline execution, state mutation, graceful degradation, Verifier override, per-incident isolation, and FastAPI concurrency status polling.

## Files created
- `sandbox/Dockerfile`: Docker container specification using `python:3.11-slim`.
- `sandbox/execute_action.py`: Action state transition script running inside container.
- `sandbox/executor.py`: Host Docker runner module exposing `execute_action_in_sandbox()`.
- `agents/verifier.py`: Verifier Agent comparing before/after metrics with local sanity check override.
- `agents/communicator.py`: Communicator Agent generating prose postmortems from incident event logs.
- `demo_scripts/test_phase3.py`: Integration test suite for Phase 3 closed-loop pipeline.
- `PHASE_3_SUMMARY.md`: Phase completion report.

## Test results
- Test 1 (Auto-Approved Pipeline): `PASS` - `read_metrics` auto-approved flow automatically executed `remediating` -> `verifying` -> `communicating` -> `done` with non-empty postmortem text.
- Test 2 (Risky Action Pipeline & state.json Mutation): `PASS` - `restart_service` paused at `awaiting_approval`, advanced automatically after `/confirm` through `remediating` -> `verifying` -> `communicating` -> `done`, generating postmortem and mutating `state.json` (`status="healthy"`, `cpu_percent` 11.1%, `error_rate` 0.012).
- Test 3 (Policy Gateway Connection Failure): `PASS` - Policy Gateway connection error cleanly set status to `failed` with clear error log message.
- Test 4 (Docker Sandbox Failure): `PASS` - Docker sandbox failure cleanly set status to `failed` without attempting verification.
- Test 5 (Verifier Local Sanity Check Override): `PASS` - Local sanity check correctly overrode invalid LLM verdict on degraded metrics to `resolved=False` with `[OVERRIDE]` note.
- Test 6 (Remediator Action Types Preserved): `PASS` - Remediator dynamic extraction preserved 13 action types from `rules.yaml`.
- Test 7 (Per-Incident State Isolation): `PASS` - Incident B (`"incident-beta"`) received a fresh degraded baseline (`status="degraded"`, `cpu_percent=92.0%`) independent of Incident A's (`"incident-alpha"`) resolved healthy state (`status="healthy"`).
- Test 8 (FastAPI Concurrency Polling): `PASS` - Polled 3 distinct intermediate status values (`remediating`, `verifying`, `communicating`) during in-flight `/confirm` execution.

## Self-verification results
- `demo_scripts/test_phase3.py` executed: 8/8 PASS.
- Per-incident state isolation confirmed: `state.json` accurately stores multiple `incident_id` keys without cross-incident state leakage.
- Concurrency confirmed: Sync FastAPI handlers allow concurrent polling of intermediate state transitions via thread pool execution.
- Single Git commit amended: `"Phase 3: sandboxed execution, verifier, and communicator agents"`, no remote configured.

## Anything ambiguous or skipped
- Note: The Verifier local sanity check catches false-positive resolutions where metrics remain degraded or worsen, but does not flag partial improvements that remain nominally degraded (e.g. `throttle_process` reducing CPU by 50% without dropping below 40%). This is an accepted, documented scope boundary for Phase 3.
