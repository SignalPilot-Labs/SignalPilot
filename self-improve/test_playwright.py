import json, urllib.request
body = json.dumps({
    "prompt": "Use the Playwright MCP browser tools to navigate to http://host.docker.internal:3400 (the self-improve monitor UI). Take a screenshot, then get the accessibility snapshot of the page. Report what you see — what elements are on the page, what the layout looks like, and whether the page loaded successfully. Do NOT write any code or files — just browse and report.",
    "max_budget_usd": 3,
    "duration_minutes": 0,
    "base_branch": "main",
}).encode()
req = urllib.request.Request("http://localhost:3401/api/agent/start", data=body, headers={"Content-Type": "application/json"}, method="POST")
print(json.dumps(json.loads(urllib.request.urlopen(req).read()), indent=2))
