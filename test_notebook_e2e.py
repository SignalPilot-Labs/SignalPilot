"""E2E test: Frontend -> Projects -> Open IDE -> confirm marimo loads."""

import httpx
import subprocess
import time
import sys

from playwright.sync_api import sync_playwright

GATEWAY = "http://localhost:3300"
FRONTEND = "http://localhost:3200"
API_KEY = "sp_4ec5fc033abfc255ee81609443ab9ba1"


def cleanup():
    print("[cleanup] Clearing sessions and pods...")
    try:
        httpx.delete(f"{GATEWAY}/api/notebook-sessions",
                     headers={"X-API-Key": API_KEY}, timeout=10)
    except Exception:
        pass
    subprocess.run(
        ["docker", "exec", "signalpilot-k3s-1", "sh", "-c",
         "kubectl delete pods --all --force --grace-period=0 2>&1;"
         "kubectl delete svc -l app=signalpilot-notebook 2>&1"],
        capture_output=True, timeout=15)
    subprocess.run(
        ["docker", "exec", "signalpilot-db-1", "psql", "-U", "signalpilot",
         "-d", "signalpilot", "-c", "DELETE FROM gateway_notebook_sessions;"],
        capture_output=True, timeout=10)
    time.sleep(3)
    print("[cleanup] Done\n")


def fail(msg, page=None, browser=None):
    print(f"\nFAIL: {msg}")
    if page:
        try:
            page.screenshot(path="e2e_fail.png")
            print("Screenshot: e2e_fail.png")
        except Exception:
            pass
    if browser:
        browser.close()
    sys.exit(1)


def main():
    print("E2E: Frontend -> Projects -> Open IDE -> Marimo\n")

    for url, name in [(GATEWAY, "Gateway"), (FRONTEND, "Frontend")]:
        try:
            httpx.get(url, timeout=5)
        except Exception:
            print(f"{name} NOT RUNNING at {url}")
            sys.exit(1)

    cleanup()

    browser = None
    page = None

    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=False, slow_mo=200)
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        # 1. Projects page
        print("[1] Projects page...")
        page.goto(f"{FRONTEND}/projects", wait_until="networkidle", timeout=10000)
        print(f"    {page.url}")

        # 2. Click Open IDE
        print("[2] Click Open IDE...")
        btn = page.locator("button:has-text('IDE')")
        if btn.count() == 0:
            fail("Open IDE button not found", page, browser)
        btn.first.click()
        print("    clicked")

        # 3. Wait for iframe
        print("[3] Waiting for iframe (60s max)...")
        try:
            page.wait_for_selector("iframe", timeout=60000)
        except Exception:
            fail("iframe never appeared", page, browser)
        print("    iframe found")

        # 4. Wait for marimo to actually serve content (poll iframe)
        print("[4] Waiting for marimo to load in iframe (30s max)...")
        deadline = time.time() + 30
        loaded = False
        while time.time() < deadline:
            child_frames = [f for f in page.frames if f != page.main_frame]
            if child_frames:
                frame = child_frames[0]
                try:
                    body = frame.inner_text("body", timeout=2000)
                    if "Proxy error" in body or "detail" in body[:50]:
                        print(f"    pod not ready: {body[:80]}")
                        page.wait_for_timeout(3000)
                        # Reload iframe
                        iframe_el = page.query_selector("iframe")
                        if iframe_el:
                            src = iframe_el.get_attribute("src")
                            if src:
                                iframe_el.evaluate(f"el => el.src = el.src")
                        continue
                    if len(body) > 50:
                        loaded = True
                        break
                except Exception:
                    pass
            page.wait_for_timeout(2000)

        if not loaded:
            fail("marimo did not render in iframe within 30s", page, browser)

        # 5. Check marimo content
        print("[5] Checking marimo content...")
        frame = [f for f in page.frames if f != page.main_frame][0]
        has_root = frame.query_selector("#root") is not None
        print(f"    #root: {has_root}")
        print(f"    frame URL: {frame.url[:80]}")

        page.screenshot(path="e2e_final.png")

        wrong_host = [e for e in errors if ":30" in e and ":3300" not in e and ":3200" not in e and "cdn" not in e]
        print(f"\n    Console errors: {len(errors)}")
        print(f"    Wrong-host: {len(wrong_host)}")

        if has_root and len(wrong_host) == 0:
            print("\nPASS: marimo loaded in iframe, all requests to correct host")
        else:
            print("\nFAIL: see above")

        browser.close()
        pw.stop()
        return 0 if has_root else 1

    except Exception as e:
        print(f"\nCRASH: {e}")
        if browser:
            browser.close()
        sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())
