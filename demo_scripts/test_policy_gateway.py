import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
import policy_gateway.main as main
from policy_gateway.expression_evaluator import evaluate_condition, ExpressionSecurityError

def test_expression_evaluator_security():
    print("\n=== Expression Evaluator Security Test ===")
    malicious_condition = '__import__("os").system("calc")'
    context = {"action": {"type": "read_logs"}}
    try:
        evaluate_condition(malicious_condition, context)
        print("[FAIL] Expression evaluator allowed disallowed function call AST node!")
        return False
    except ExpressionSecurityError as e:
        print(f"[PASS] ExpressionSecurityError correctly caught disallowed AST node: {e}")
        return True
    except Exception as e:
        print(f"[FAIL] Unexpected exception type: {e}")
        return False

def run_tests():
    passed = 0
    total = 5

    print("=== Aegis Policy Gateway Test Suite ===")
    
    client = TestClient(main.app)

    # Test 1: read_logs -> auto-approve
    try:
        resp = client.post("/evaluate", json={"action_type": "read_logs", "payload": {"target": "auth-service"}})
        data = resp.json()
        if resp.status_code == 200 and data.get("verdict") == "auto-approve" and data.get("deciding_rule") == "readonly-auto-approve":
            print("[PASS] Case 1: read_logs -> auto-approve (rule: readonly-auto-approve)")
            passed += 1
        else:
            print(f"[FAIL] Case 1: Expected auto-approve, got {data}")
    except Exception as e:
        print(f"[FAIL] Case 1: Request failed: {e}")

    # Test 2: restart_service -> needs-approval, confirm -> approved
    try:
        resp = client.post("/evaluate", json={"action_type": "restart_service", "payload": {"service": "payment"}})
        data = resp.json()
        token = data.get("token")
        if resp.status_code == 200 and data.get("verdict") == "needs-approval" and token:
            confirm_resp = client.post(f"/confirm/{token}")
            c_data = confirm_resp.json()
            if confirm_resp.status_code == 200 and c_data.get("result") == "approved":
                print("[PASS] Case 2: restart_service -> needs-approval & confirm -> approved")
                passed += 1
            else:
                print(f"[FAIL] Case 2: Confirm failed, got {c_data}")
        else:
            print(f"[FAIL] Case 2: Evaluate failed, got {data}")
    except Exception as e:
        print(f"[FAIL] Case 2: Request failed: {e}")

    # Test 3: delete_database -> deny
    try:
        resp = client.post("/evaluate", json={"action_type": "delete_database", "payload": {"db": "production"}})
        data = resp.json()
        if resp.status_code == 200 and data.get("verdict") == "deny" and data.get("deciding_rule") == "destructive-deny":
            print("[PASS] Case 3: delete_database -> deny (rule: destructive-deny)")
            passed += 1
        else:
            print(f"[FAIL] Case 3: Expected deny, got {data}")
    except Exception as e:
        print(f"[FAIL] Case 3: Request failed: {e}")

    # Test 4: launch_nuke -> deny with deciding_rule default-deny-fail-closed
    try:
        resp = client.post("/evaluate", json={"action_type": "launch_nuke", "payload": {}})
        data = resp.json()
        if resp.status_code == 200 and data.get("verdict") == "deny" and data.get("deciding_rule") == "default-deny-fail-closed":
            print("[PASS] Case 4: launch_nuke -> deny (rule: default-deny-fail-closed)")
            passed += 1
        else:
            print(f"[FAIL] Case 4: Expected default-deny-fail-closed, got {data}")
    except Exception as e:
        print(f"[FAIL] Case 4: Request failed: {e}")

    # Test 5: throttle_process -> monkeypatch APPROVAL_TOKEN_TTL_SECONDS = 0.1 for test run -> wait 0.25s -> confirm -> expired
    orig_ttl = main.APPROVAL_TOKEN_TTL_SECONDS
    try:
        main.APPROVAL_TOKEN_TTL_SECONDS = 0.1
        resp = client.post("/evaluate", json={"action_type": "throttle_process", "payload": {"pid": 1234}})
        data = resp.json()
        token = data.get("token")
        if resp.status_code == 200 and data.get("verdict") == "needs-approval" and token:
            time.sleep(0.25)
            confirm_resp = client.post(f"/confirm/{token}")
            c_data = confirm_resp.json()
            if confirm_resp.status_code == 200 and c_data.get("result") == "expired":
                print("[PASS] Case 5: throttle_process -> needs-approval & confirm after TTL -> expired")
                passed += 1
            else:
                print(f"[FAIL] Case 5: Expected expired, got {c_data}")
        else:
            print(f"[FAIL] Case 5: Evaluate failed, got {data}")
    except Exception as e:
        print(f"[FAIL] Case 5: Request failed: {e}")
    finally:
        main.APPROVAL_TOKEN_TTL_SECONDS = orig_ttl

    sec_pass = test_expression_evaluator_security()

    print(f"\nResult: {passed}/{total} suite tests passed. Security check: {'PASS' if sec_pass else 'FAIL'}")
    if passed == total and sec_pass:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
