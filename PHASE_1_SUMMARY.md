# Phase 1 Summary

## Fix applied
- Removed `ttl_seconds` parameter from `EvaluateRequest` model in `policy_gateway/main.py` so token TTL cannot be controlled by API callers.
- Defined fixed module-level constant `APPROVAL_TOKEN_TTL_SECONDS = 120` in `policy_gateway/main.py`.
- Updated `evaluate_action` to always compute `expires_at` using `APPROVAL_TOKEN_TTL_SECONDS`.
- Updated `demo_scripts/test_policy_gateway.py` to temporarily monkeypatch `main.APPROVAL_TOKEN_TTL_SECONDS = 0.1` in-process during test case 5 to verify expiry behavior deterministically without a 120-second sleep.

## What was done
- Implemented a self-built restricted AST expression evaluator in `policy_gateway/expression_evaluator.py` that parses and evaluates rule conditions while strictly enforcing a node type whitelist (rejecting function calls, arithmetic, and imports).
- Created `policy_gateway/rules.yaml` containing the 3 explicit rule definitions (`readonly-auto-approve`, `risky-needs-approval`, `destructive-deny`) in exact order, with engine-level fallback (`default-deny-fail-closed`).
- Implemented SQLite audit logging in `policy_gateway/main.py` referencing `SQLITE_DB_PATH` (`./audit_log/aegis_audit.db`), recording timestamp, action_type, action_payload, verdict, deciding_rule, and token.
- Implemented the `CONFIRM_REQUIRED` token flow with 2-minute fixed TTL (`APPROVAL_TOKEN_TTL_SECONDS = 120`) storing pending tokens in memory and handling approval/expiration transitions.
- Created FastAPI app in `policy_gateway/main.py` exposing exactly `POST /evaluate` and `POST /confirm/{token}` running on `127.0.0.1:8001`.
- Built and ran `demo_scripts/test_policy_gateway.py` verifying all 5 test cases and expression evaluator security rejection.

## Files created
- `policy_gateway/expression_evaluator.py`: AST-based restricted condition evaluator with strict node whitelisting.
- `policy_gateway/rules.yaml`: YAML configuration defining the 3 policy rules and verdicts.
- `policy_gateway/main.py`: FastAPI server handling `/evaluate` and `/confirm/{token}` endpoints with SQLite audit logging and token management.
- `demo_scripts/test_policy_gateway.py`: Test suite verifying the 5 gateway cases and AST security isolation.

## Rule evaluation test results
- Case 1 (`read_logs`): PASS - Actual verdict: `auto-approve` (deciding_rule: `readonly-auto-approve`)
- Case 2 (`restart_service`): PASS - Actual verdict: `needs-approval` (token generated) & `/confirm/{token}` -> `approved`
- Case 3 (`delete_database`): PASS - Actual verdict: `deny` (deciding_rule: `destructive-deny`)
- Case 4 (`launch_nuke`): PASS - Actual verdict: `deny` (deciding_rule: `default-deny-fail-closed`)
- Case 5 (`throttle_process`): PASS - Actual verdict: `needs-approval` (token generated with fixed TTL) & `/confirm/{token}` -> `expired` (verified via in-process monkeypatched TTL = 0.1s)

## Audit log verification
- Queried `audit_log/aegis_audit.db` directly and confirmed all audit log entries exist and match expected values:
  - `read_logs` | `auto-approve` | `readonly-auto-approve` | `token: None`
  - `restart_service` | `needs-approval` | `risky-needs-approval` | `token: 34c9179e...`
  - `restart_service` | `approved` | `risky-needs-approval` | `token: 34c9179e...`
  - `delete_database` | `deny` | `destructive-deny` | `token: None`
  - `launch_nuke` | `deny` | `default-deny-fail-closed` | `token: None`
  - `throttle_process` | `needs-approval` | `risky-needs-approval` | `token: e19ebf7b...`
  - `throttle_process` | `expired` | `risky-needs-approval` | `token: e19ebf7b...`

## Expression evaluator security check result
- PASS: Evaluator rejected malicious condition `__import__("os").system("calc")` by raising `ExpressionSecurityError` due to disallowed `Call` AST node.

## Self-verification results
- FastAPI server running on `127.0.0.1:8001` and `test_policy_gateway.py` executed with 5/5 cases PASS: PASS
- SQLite database `audit_log/aegis_audit.db` verified with exact expected rows and columns: PASS
- Expression evaluator security check verified (disallowed AST nodes rejected): PASS
- Git repository updated with amended commit `"Phase 1: policy gateway rule engine and audit log"`, no remote configured: PASS

## Anything ambiguous or skipped
- None. All specifications executed strictly as required.
