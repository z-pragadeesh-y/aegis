import os
import sys
import time
import json
import glob
import shutil
import httpx
from playwright.sync_api import sync_playwright

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO_DIR = os.path.join(ROOT_DIR, "demo_scripts", "video_scratch")
OUTPUT_VIDEO_PATH = os.path.join(ROOT_DIR, "demo_scripts", "backup_recording.webm")

def record_full_sequence():
    if os.path.exists(VIDEO_DIR):
        try:
            shutil.rmtree(VIDEO_DIR, ignore_errors=True)
        except Exception:
            pass
    os.makedirs(VIDEO_DIR, exist_ok=True)

    print("=========================================================================")
    print("RECORDING PLAYWRIGHT DEMO VIDEO FOR AEGIS MISSION CONTROL DASHBOARD")
    print("=========================================================================")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=VIDEO_DIR,
            record_video_size={"width": 1440, "height": 900}
        )
        page = context.new_page()

        # Step 1: Open calm dashboard view
        print("1. Navigating to http://localhost:5173 (Calm Dashboard View)...")
        page.goto("http://localhost:5173", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # Step 2: Trigger Primary Incident
        ts = int(time.time())
        inc_id_1 = f"rec-primary-{ts}"
        desc = "Connection pool exhaustion and high CPU contention on checkout worker threads"
        print(f"2. Triggering Primary Incident '{inc_id_1}' via API...")
        
        req_1 = {
            "incident_id": inc_id_1,
            "description": desc,
            "desired_action_type": "restart_service"
        }
        resp = httpx.post("http://127.0.0.1:8002/incidents", json=req_1, timeout=10.0)
        print(f"   -> Trigger response: {resp.status_code}")

        # Step 3: Wait for Approve button on UI
        print("3. Waiting for 'Approve & Execute Remediation' button on Dashboard...")
        approve_button = page.locator("button.btn-approve")
        try:
            approve_button.wait_for(state="visible", timeout=45000)
            print("   -> Approve button visible!")
            page.wait_for_timeout(2000) # Give UI moment to render reasoning trace

            # Click Approve button
            print("4. Clicking 'Approve & Execute Remediation' button on UI...")
            approve_button.click()
            page.wait_for_timeout(1000)
        except Exception as e:
            print(f"   -> Warning: Button locator wait error: {e}")

        # Step 4: Wait for incident completion to 'done'
        print("5. Watching incident progress to 'done' status...")
        done_start = time.time()
        while time.time() - done_start < 45.0:
            res = httpx.get(f"http://127.0.0.1:8002/incidents/{inc_id_1}").json()
            if res.get("status") == "done":
                print(f"   -> Primary incident completed to 'done' in {time.time() - done_start:.2f}s!")
                break
            page.wait_for_timeout(1000)
        page.wait_for_timeout(4000) # Show postmortem card on UI

        # Step 5: Trigger Second Fast-Path Incident
        inc_id_2 = f"rec-fastpath-{ts}"
        print(f"6. Triggering SECOND Incident '{inc_id_2}' (Fast-Path Memory Recall)...")
        req_2 = {
            "incident_id": inc_id_2,
            "description": desc,
            "desired_action_type": "restart_service"
        }
        httpx.post("http://127.0.0.1:8002/incidents", json=req_2, timeout=10.0)

        # Select second incident in UI list
        print("7. Selecting Fast-Path Incident on Dashboard UI...")
        page.wait_for_timeout(2000)
        try:
            fast_item = page.locator(f".incident-item:has-text('{inc_id_2}')")
            fast_item.wait_for(state="visible", timeout=10000)
            fast_item.click()
            page.wait_for_timeout(1000)
        except Exception as e:
            print(f"   -> Fast-path item click note: {e}")

        # Wait for approve button on fast-path incident
        print("8. Waiting for Fast-Path Approve button on Dashboard...")
        try:
            approve_button.wait_for(state="visible", timeout=15000)
            print("   -> Fast-Path Approve button visible!")
            page.wait_for_timeout(2000)
            approve_button.click()
        except Exception as e:
            print(f"   -> Fast-path button wait note: {e}")

        # Wait for second incident done
        done_start2 = time.time()
        while time.time() - done_start2 < 30.0:
            res = httpx.get(f"http://127.0.0.1:8002/incidents/{inc_id_2}").json()
            if res.get("status") == "done":
                print(f"   -> Fast-Path incident completed to 'done' in {time.time() - done_start2:.2f}s!")
                break
            page.wait_for_timeout(1000)
        page.wait_for_timeout(4000) # Final view

        # Close context to save video file
        page.close()
        context.close()
        browser.close()

    # Move video file to final destination
    video_files = glob.glob(os.path.join(VIDEO_DIR, "*.webm"))
    if video_files:
        src = video_files[0]
        shutil.copyfile(src, OUTPUT_VIDEO_PATH)
        size_mb = os.path.getsize(OUTPUT_VIDEO_PATH) / (1024.0 * 1024.0)
        print(f"\n[SUCCESS] BACKUP RECORDING PRODUCED SUCCESSFULLY!")
        print(f"   Path: {OUTPUT_VIDEO_PATH}")
        print(f"   File Size: {size_mb:.2f} MB")
    else:
        print("ERROR: No video file was generated by Playwright!")

if __name__ == "__main__":
    record_full_sequence()
