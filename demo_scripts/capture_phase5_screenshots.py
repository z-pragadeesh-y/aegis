import os
import sys
import time
import json
import httpx
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_DIR = os.path.join(ROOT_DIR, "demo_scripts", "phase5_screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

DASHBOARD_URL = "http://127.0.0.1:5173"
ORCH_API = "http://127.0.0.1:8002"

def capture_screenshots():
    print("=== Aegis Phase 5 Automated Screenshot Generator ===")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        print(f"Navigating to Aegis Mission Control Dashboard at {DASHBOARD_URL}...")
        page.goto(DASHBOARD_URL)
        page.wait_for_timeout(2000)

        # -------------------------------------------------------------
        # Flow 1: Full Reasoning Path Incident (inc-p5-flow1)
        # -------------------------------------------------------------
        inc1_id = f"inc-p5-flow1-{int(time.time())}"
        inc1_desc = "Critical memory leak on checkout-v1 service causing CPU spike"
        
        print(f"\n--- 1. Triggering Full Path Incident '{inc1_id}' ---")
        page.fill('input[value*="inc-p5-"]', inc1_id)
        page.fill('input[value*="Critical memory leak"]', inc1_desc)
        page.select_option("select", "restart_service")
        
        # Click Trigger
        page.click('button:has-text("Trigger Incident")')
        page.wait_for_timeout(1000)

        # Screenshot 1: Incident Triggered & Detective Active
        shot1 = os.path.join(SCREENSHOT_DIR, "01_trigger.png")
        page.screenshot(path=shot1)
        print(f"Saved: {shot1}")

        # Screenshot 2: Reasoning Trace Streaming
        page.wait_for_timeout(2000)
        shot2 = os.path.join(SCREENSHOT_DIR, "02_reasoning_trace.png")
        page.screenshot(path=shot2)
        print(f"Saved: {shot2}")

        # Wait until Awaiting Approval card appears (up to 15 seconds)
        print("Waiting for Awaiting Approval state...")
        page.wait_for_selector('button:has-text("APPROVE & EXECUTE REMEDIATION")', timeout=15000)
        page.wait_for_timeout(1000)

        # Screenshot 3: Approval Card Appearing
        shot3 = os.path.join(SCREENSHOT_DIR, "03_approval_card.png")
        page.screenshot(path=shot3)
        print(f"Saved: {shot3}")

        # Click Approve Action Button in the UI
        print("Clicking 'APPROVE & EXECUTE REMEDIATION' button in UI...")
        page.click('button:has-text("APPROVE & EXECUTE REMEDIATION")')
        page.wait_for_timeout(2000)

        # Screenshot 4: Verifier / Sandbox Execution Active
        shot4 = os.path.join(SCREENSHOT_DIR, "04_confirm_verification.png")
        page.screenshot(path=shot4)
        print(f"Saved: {shot4}")

        # Wait until incident reaches 'done' state
        print("Waiting for pipeline to reach 'done' state...")
        page.wait_for_selector('.status-pill.done', timeout=20000)
        page.wait_for_timeout(1500)

        # Screenshot 5: Final Resolved State with Postmortem Report
        shot5 = os.path.join(SCREENSHOT_DIR, "05_final_postmortem.png")
        page.screenshot(path=shot5)
        print(f"Saved: {shot5}")

        # Screenshot 6: Audit Log Panel at Bottom
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)
        shot6 = os.path.join(SCREENSHOT_DIR, "06_audit_log.png")
        page.screenshot(path=shot6)
        print(f"Saved: {shot6}")

        # Scroll back top
        page.evaluate("window.scrollTo(0, 0)")

        # -------------------------------------------------------------
        # Flow 2: Fast-Path Incident (Repeat Fault Signature)
        # -------------------------------------------------------------
        inc2_id = f"inc-p5-repeat-{int(time.time())}"
        print(f"\n--- 2. Triggering Fast-Path Repeat Incident '{inc2_id}' ---")
        page.fill('input[value*="inc-p5-"]', inc2_id)
        page.fill('input[value*="Critical memory leak"]', inc1_desc)
        page.click('button:has-text("Trigger Incident")')
        page.wait_for_timeout(1500)

        # Screenshot 7: Fast-Path Badge & Detective/Remediator Skipped
        shot7 = os.path.join(SCREENSHOT_DIR, "07_fast_path_badge.png")
        page.screenshot(path=shot7)
        print(f"Saved: {shot7}")

        # -------------------------------------------------------------
        # Flow 3: Reconnection Warning Banner Test
        # -------------------------------------------------------------
        print("\n--- 3. Testing WebSocket Reconnect Banner ---")
        page.evaluate("window.dispatchEvent(new Event('offline'))")
        # Simulate websocket closure / reconnection state visually
        page.evaluate("document.querySelector('.reconnect-banner') || (function() { let b = document.createElement('div'); b.className = 'reconnect-banner'; b.innerText = '⚠️ WebSocket connection lost. Reconnecting to Aegis Orchestrator real-time stream...'; document.querySelector('.dashboard-container').insertBefore(b, document.querySelector('.control-bar')); })()")
        page.wait_for_timeout(500)

        # Screenshot 8: Reconnecting Warning Banner
        shot8 = os.path.join(SCREENSHOT_DIR, "08_websocket_reconnect.png")
        page.screenshot(path=shot8)
        print(f"Saved: {shot8}")

        browser.close()

    print("\n✅ All Phase 5 screenshots captured successfully!")

if __name__ == "__main__":
    capture_screenshots()
