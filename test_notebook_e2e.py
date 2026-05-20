"""E2E test: Frontend -> Projects -> Open IDE -> marimo loads directly via NodePort."""

import httpx
import subprocess
import time
import sys

from playwright.sync_api import sync_playwright

GATEWAY = "http://localhost:3300"
FRONTEND = "http://localhost:3200"
API_KEY = "YOUR_API_KEY_HERE"


def cleanup():
    print("[cleanup] Clearing sessions and pods...")
    try:
        httpx.delete(f"{GATEWAY}/api/notebook-sessions", headers={"X-API-Key": API_KEY}, timeout=10)
    except Exception:
        pass
    subprocess.run(["docker", "exec", "signalpilot-k3s-1", "sh", "-c",
        "kubectl delete pods --all --force --grace-period=0 2>&1; kubectl delete svc -l app=signalpilot-notebook 2>&1"],
        capture_output=True, timeout=15)
    subprocess.run(["docker", "exec", "signalpilot-db-1", "psql", "-U", "signalpilot", "-d", "signalpilot",
        "-c", "DELETE FROM gateway_notebook_sessions;"], capture_output=True, timeout=10)
    time.sleep(3)


def fail(msg, page=None, browser=None):
    print(f"FAIL: {msg}")
    if page:
        try: page.screenshot(path="e2e_fail.png")
        except: pass
    if browser:
        browser.close()
    sys.exit(1)


def main():
    print("E2E: Frontend -> Open IDE -> Marimo via NodePort\n")

    for url, name in [(GATEWAY, "Gateway"), (FRONTEND, "Frontend")]:
        try: httpx.get(url, timeout=5)
        except: fail(f"{name} not running at {url}")

    cleanup()

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False, slow_mo=200)
    page = browser.new_page(viewport={"width": 1400, "height": 900})

    try:
        # 1. Projects page
        print("[1] Projects page...")
        page.goto(f"{FRONTEND}/projects", wait_until="networkidle", timeout=10000)

        # 2. Click Open IDE
        print("[2] Click Open IDE...")
        btn = page.locator("button:has-text('IDE')")
        if btn.count() == 0:
            fail("Open IDE button not found", page, browser)
        btn.first.click()

        # 3. Wait for iframe
        print("[3] Waiting for iframe (90s)...")
        try:
            page.wait_for_selector("iframe", timeout=90000)
        except:
            fail("iframe never appeared", page, browser)

        # 4. Poll iframe until marimo renders
        print("[4] Waiting for marimo to load (45s)...")
        deadline = time.time() + 45
        loaded = False
        while time.time() < deadline:
            frames = [f for f in page.frames if f != page.main_frame]
            if frames:
                frame = frames[0]
                try:
                    body = frame.inner_text("body", timeout=2000)
                    if len(body) > 100 and "error" not in body.lower()[:50]:
                        loaded = True
                        break
                except:
                    pass
            page.wait_for_timeout(3000)

        if not loaded:
            fail("marimo did not render within 45s", page, browser)

        # 5. Verify
        print("[5] Verifying marimo content...")
        frame = [f for f in page.frames if f != page.main_frame][0]
        has_root = frame.query_selector("#root") is not None
        url = frame.url
        print(f"    frame URL: {url[:80]}")
        print(f"    #root: {has_root}")

        # Check iframe src points to NodePort, not gateway proxy
        iframe_el = page.query_selector("iframe")
        src = iframe_el.get_attribute("src") if iframe_el else ""
        is_direct = "localhost:30" in src
        print(f"    iframe src: {src[:80]}")
        print(f"    direct NodePort: {is_direct}")

        page.screenshot(path="e2e_final.png")

        if has_root and is_direct:
            print("\nPASS: marimo loaded via direct NodePort")
        else:
            print("\nFAIL: check above")

        browser.close()
        pw.stop()
        return 0 if (has_root and is_direct) else 1

    except Exception as e:
        print(f"CRASH: {e}")
        browser.close()
        pw.stop()
        return 1


if __name__ == "__main__":
    sys.exit(main())
