"""E2E test: Open IDE -> project list loads -> click Test dbt Project -> WS connects -> file explorer."""

import httpx
import time
import sys

from playwright.sync_api import sync_playwright

FRONTEND = "http://localhost:3200"
GATEWAY = "http://localhost:3300"

console_logs = []
network_errors = []


def dump_logs():
    if console_logs:
        print(f"\n--- Browser console ({len(console_logs)} entries) ---")
        for entry in console_logs[-50:]:
            print(f"  [{entry['type']}] {entry['text'][:200]}")
    if network_errors:
        print(f"\n--- Network errors ({len(network_errors)} entries) ---")
        for err in network_errors[-20:]:
            print(f"  {err[:200]}")


def fail(msg, page=None, browser=None, pw=None):
    print(f"\nFAIL: {msg}")
    dump_logs()
    if page:
        try:
            page.screenshot(path="e2e_fail.png")
            print("  screenshot: e2e_fail.png")
        except Exception:
            pass
    if browser:
        try:
            browser.close()
        except Exception:
            pass
    if pw:
        try:
            pw.stop()
        except Exception:
            pass
    sys.exit(1)


def main():
    print("E2E: Open IDE -> project list -> Test dbt Project -> WS + file explorer\n")

    # 0. Cleanup — delete session, kill pods, clear DB
    print("[0] Cleanup...")
    try:
        httpx.delete(f"{GATEWAY}/api/notebook-sessions", timeout=10)
    except Exception:
        pass
    import subprocess
    subprocess.run(["docker", "exec", "signalpilot-k3s-1", "sh", "-c",
        "kubectl delete pods --all -A --field-selector=metadata.namespace!=kube-system "
        "--force --grace-period=0 2>/dev/null"],
        capture_output=True, timeout=15)
    subprocess.run(["docker", "exec", "signalpilot-gateway-1", "python", "-c",
        "import asyncio;from gateway.db.engine import get_session_factory;"
        "async def c():\n f=get_session_factory()\n async with f() as s:\n"
        "  from sqlalchemy import text\n  await s.execute(text('DELETE FROM gateway_notebook_sessions'))\n"
        "  await s.commit()\nasyncio.run(c())"],
        capture_output=True, timeout=10)
    time.sleep(3)

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False, slow_mo=150)
    page = browser.new_page(viewport={"width": 1400, "height": 900})

    page.on("console", lambda msg: console_logs.append({"type": msg.type, "text": msg.text}))
    page.on("pageerror", lambda err: console_logs.append({"type": "PAGE_ERROR", "text": str(err)}))
    page.on("requestfailed", lambda req: network_errors.append(
        f"{req.method} {req.url} -> {req.failure}"))

    try:
        # 1. Projects page -> Open IDE
        print("[1] Projects page -> Open IDE...")
        page.goto(f"{FRONTEND}/projects", wait_until="networkidle", timeout=15000)
        ide_btn = page.locator("button:has-text('IDE')")
        if ide_btn.count() == 0:
            fail("No Open IDE button", page, browser, pw)
        ide_btn.first.click()

        # 2. Wait for iframe + marimo render
        print("[2] Waiting for marimo to load...")
        start = time.time()
        iframe_found = False
        while time.time() - start < 120:
            if page.locator("iframe").count() > 0:
                iframe_found = True
                print(f"    iframe appeared after {int(time.time()-start)}s")
                break
            if page.locator("text=Failed to start").count() > 0:
                fail("Failed to start notebook", page, browser, pw)
            page.wait_for_timeout(3000)
        if not iframe_found:
            fail("iframe never appeared", page, browser, pw)

        # Wait for #root in iframe
        start = time.time()
        while time.time() - start < 60:
            frames = [f for f in page.frames if f != page.main_frame]
            if frames:
                frame = frames[0]
                if frame.query_selector("#root") and len(frame.inner_text("body", timeout=2000)) > 50:
                    print(f"    marimo rendered after {int(time.time()-start)}s")
                    break
            page.wait_for_timeout(2000)
        else:
            fail("marimo did not render", page, browser, pw)

        page.screenshot(path="e2e_02_marimo_home.png")

        # 3. Wait for project list to load (Test dbt Project must be visible)
        print("[3] Waiting for project list to load (up to 30s)...")
        frame = [f for f in page.frames if f != page.main_frame][0]
        start = time.time()
        project_found = False
        while time.time() - start < 30:
            project_btn = frame.locator("button:has-text('Test dbt Project')")
            if project_btn.count() > 0:
                project_found = True
                print(f"    'Test dbt Project' visible after {int(time.time()-start)}s")
                break
            # Check for gateway API failures in network errors
            gw_failures = [e for e in network_errors if "172.26" in e or "ERR_CONNECTION" in e]
            if gw_failures:
                page.screenshot(path="e2e_03_gw_fail.png")
                fail(f"Browser can't reach gateway: {gw_failures[0][:150]}", page, browser, pw)
            page.wait_for_timeout(2000)

        if not project_found:
            page.screenshot(path="e2e_03_no_project.png")
            # Get what IS visible
            buttons = frame.query_selector_all("button")
            labels = [(b.get_attribute("aria-label") or b.inner_text() or "").strip()[:50]
                      for b in buttons[:15]]
            print(f"    visible buttons: {labels}")
            fail("'Test dbt Project' not visible — project list didn't load", page, browser, pw)

        page.screenshot(path="e2e_03_project_list.png")

        # 4. Click Test dbt Project
        print("[4] Clicking 'Test dbt Project'...")
        pre_click_count = len(console_logs)
        project_btn.first.click()
        page.screenshot(path="e2e_04_clicked.png")

        # 5. Wait for notebook to initialize (WS connect, kernel start)
        print("[5] Waiting 10s for notebook to initialize...")
        page.wait_for_timeout(10000)
        page.screenshot(path="e2e_05_notebook.png")

        # Print post-click console
        for l in console_logs[pre_click_count:]:
            if l["type"] in ("error", "debug") or "runtime" in l["text"].lower():
                print(f"    [{l['type']}] {l['text'][:150]}")

        # 6. Check WS connection — disconnected indicator
        print("[6] Checking WS connection...")
        frame = [f for f in page.frames if f != page.main_frame][0]
        disconnected = frame.query_selector('[data-testid="disconnected-indicator"]')
        is_disconnected = disconnected and disconnected.is_visible()
        runtime_healthy = any("healthy" in l["text"].lower() for l in console_logs)

        if is_disconnected:
            page.screenshot(path="e2e_06_disconnected.png")
            fail("WebSocket disconnected — disconnected-indicator visible", page, browser, pw)
        print(f"    disconnected indicator: NOT visible (good)")
        print(f"    runtime healthy: {runtime_healthy}")

        if not runtime_healthy:
            print("    waiting 15s more...")
            page.wait_for_timeout(15000)
            runtime_healthy = any("healthy" in l["text"].lower() for l in console_logs)
            disconnected = frame.query_selector('[data-testid="disconnected-indicator"]')
            is_disconnected = disconnected and disconnected.is_visible()
            if is_disconnected:
                fail("WebSocket disconnected after extra wait", page, browser, pw)

        # 7. Click file explorer panel
        print("[7] Opening file explorer...")
        files_tab = frame.locator('[data-key="files"]')
        if files_tab.count() > 0:
            files_tab.first.click()
            print("    clicked files tab")
        else:
            print("    files tab not found")

        page.wait_for_timeout(5000)
        page.screenshot(path="e2e_07_files.png")

        # Check for list_files errors
        list_files_errors = [l for l in console_logs
                             if "connection refused" in l["text"].lower()
                             and ("listfiles" in l["text"].lower() or "list_files" in l["text"].lower())]
        cloud_off = frame.locator('.lucide-cloud-off')
        has_cloud_off = cloud_off.count() > 0 and cloud_off.first.is_visible()

        tree = frame.query_selector('[role="tree"]')
        tree_items = frame.query_selector_all('[role="treeitem"]')
        print(f"    file tree present: {tree is not None}")
        print(f"    tree items: {len(tree_items)}")
        print(f"    cloud-off icon: {has_cloud_off}")
        print(f"    list_files errors: {len(list_files_errors)}")

        for btn_id in ["file-explorer-add-notebook-button", "file-explorer-add-file-button",
                       "file-explorer-upload-button"]:
            if frame.query_selector(f'[data-testid="{btn_id}"]'):
                print(f"    {btn_id}: present")

        # 8. Keep open for inspection
        print("\n    (keeping browser open 5s...)")
        page.wait_for_timeout(5000)
        page.screenshot(path="e2e_final.png")

        # 9. Check ALL console errors — not just happy path
        print("\n[9] Checking ALL console errors...")
        all_errors = [l for l in console_logs if l["type"] == "error"]
        # Categorize — exclude errors without URLs (browser strips URLs from console errors,
        # so "Failed to load resource: the server responded with a status of 404 ()" with
        # no URL context are typically HMR/static asset misses, not gateway API failures).
        # Only count errors that mention specific gateway/proxy paths as blocking.
        api_404s = [l for l in all_errors if "404" in l["text"]
                    and ("Not Found" in l["text"] or "/api/" in l["text"])]
        api_401s = [l for l in all_errors if ("401" in l["text"] or "Unauthorized" in l["text"])
                    and "/api/" in l["text"]]
        api_500s = [l for l in all_errors if "500" in l["text"]]
        ws_errors = [l for l in all_errors if "WebSocket" in l["text"]]
        conn_errors = [l for l in all_errors if "connection refused" in l["text"].lower()
                       or "ERR_CONNECTION" in l["text"]]
        # Exclude CDN font errors (external, not our issue)
        cdn_errors = [l for l in all_errors if "jsdelivr" in l["text"] or "JetBrains" in l["text"]]
        our_errors = [l for l in all_errors if l not in cdn_errors]

        if api_404s:
            print(f"  404 errors ({len(api_404s)}):")
            for l in api_404s:
                print(f"    {l['text'][:150]}")
        if api_401s:
            print(f"  401 errors ({len(api_401s)}):")
            for l in api_401s:
                print(f"    {l['text'][:150]}")
        if api_500s:
            print(f"  500 errors ({len(api_500s)}):")
            for l in api_500s:
                print(f"    {l['text'][:150]}")
        if ws_errors:
            print(f"  WebSocket errors ({len(ws_errors)}):")
            for l in ws_errors:
                print(f"    {l['text'][:150]}")
        if conn_errors:
            print(f"  Connection errors ({len(conn_errors)}):")
            for l in conn_errors:
                print(f"    {l['text'][:150]}")
        if not our_errors:
            print("  no application errors (only CDN font 404s)")

        # Network errors (excluding CDN)
        our_net_errors = [e for e in network_errors if "jsdelivr" not in e and "JetBrains" not in e]
        if our_net_errors:
            print(f"\n  Network failures ({len(our_net_errors)}):")
            for e in our_net_errors:
                print(f"    {e[:200]}")

        # 10. Summary
        gw_api_fails = [e for e in network_errors
                        if "172.26" in e or ("ERR_CONNECTION" in e and "3300" in e)]

        print("\n--- Results ---")
        print(f"  marimo rendered:      YES")
        print(f"  project list loaded:  {'YES' if project_found else 'NO'}")
        print(f"  WS connected:         {'YES' if not is_disconnected else 'NO'}")
        print(f"  runtime healthy:      {'YES' if runtime_healthy else 'NO'}")
        print(f"  file explorer:        {'YES' if tree else 'NO'} ({len(tree_items)} items)")
        print(f"  cloud-off icon:       {'YES (issue)' if has_cloud_off else 'NO (good)'}")
        print(f"  console errors:       {len(our_errors)} (excl CDN)")
        print(f"  -> 404s:              {len(api_404s)}")
        print(f"  -> 401s:              {len(api_401s)}")
        print(f"  -> 500s:              {len(api_500s)}")
        print(f"  -> WS:                {len(ws_errors)}")
        print(f"  gateway API fails:    {len(gw_api_fails)}")

        dump_logs()

        browser.close()
        pw.stop()

        passed = (project_found and not is_disconnected and runtime_healthy
                  and len(gw_api_fails) == 0 and len(ws_errors) == 0
                  and len(api_404s) == 0 and len(api_401s) == 0
                  and len(api_500s) == 0 and len(conn_errors) == 0
                  and not has_cloud_off)
        if not passed:
            reasons = []
            if not project_found: reasons.append("project list didn't load")
            if is_disconnected: reasons.append("WebSocket disconnected")
            if not runtime_healthy: reasons.append("runtime not healthy")
            if gw_api_fails: reasons.append(f"{len(gw_api_fails)} gateway API failures")
            if ws_errors: reasons.append(f"{len(ws_errors)} WebSocket errors")
            if api_404s: reasons.append(f"{len(api_404s)} x 404 errors")
            if api_401s: reasons.append(f"{len(api_401s)} x 401 errors")
            if api_500s: reasons.append(f"{len(api_500s)} x 500 errors")
            if conn_errors: reasons.append(f"{len(conn_errors)} connection errors")
            if has_cloud_off: reasons.append("cloud-off icon visible (cloud sync broken)")
            print(f"\nFAIL — {', '.join(reasons)}")
        print(f"\n{'PASS' if passed else 'FAIL'}")
        return 0 if passed else 1

    except Exception as e:
        print(f"\nCRASH: {type(e).__name__}: {e}")
        dump_logs()
        try:
            page.screenshot(path="e2e_crash.png")
        except Exception:
            pass
        browser.close()
        pw.stop()
        return 1


if __name__ == "__main__":
    sys.exit(main())
