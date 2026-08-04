// Capture the /evals page with live data and simulated scale data.
import { chromium } from "playwright";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1720, height: 1300 } });

// Capture data from the active service.
await page.goto("http://localhost:3260/evals", { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
await page.screenshot({ path: "e2e-evals-redesign-real.png", fullPage: false });

// Simulate 180 tasks, 40 runs, and accuracy history.
const kinds = ["metric", "reconcile", "control", "build"];
const tasks = Array.from({ length: 180 }, (_, i) => {
  const cls = i % 4 === 3 ? "write" : "read";
  return {
    id: `t-${String(i + 1).padStart(3, "0")}_${["revenue", "claims", "orders", "sessions"][i % 4]}`,
    class: cls,
    kind: kinds[i % kinds.length],
    gt: "42",
    title: `Task ${i + 1}: total ${["revenue", "claims", "orders", "sessions"][i % 4]} for segment ${i % 12}`,
    why: i % 4 === 2 ? "control task" : "trap",
    prompt: `What is the total for segment ${i}?`,
    doc: i % 3 === 0 ? `# Task ${i + 1} writeup\n\nDetails.` : "",
    checks: i % 5 === 0 ? [] : [{ name: "total", value: 1000 + i, tolerance: 0.01 }],
    grade:
      cls === "write"
        ? { kind: "model_rebuilt", expectations: [{ name: "row_count", value: 5000 + i, tolerance: 0.0 }] }
        : { kind: "checks" },
    covers: [`mart_${["revenue", "claims", "orders", "sessions"][i % 4]}`],
    builds: cls === "write" ? [`mart_rebuild_${i % 12}`] : [],
    capture:
      cls === "write"
        ? { tables: [`mart_rebuild_${i % 12}`], mode: "full", sample_rows: 50 }
        : null,
    setup: cls === "write" ? `setup/t-${i + 1}.sh` : "",
    teardown: cls === "write" ? `teardown/t-${i + 1}.sh` : "",
  };
});

const runs = Array.from({ length: 40 }, (_, i) => ({
  id: `run-2026073${i % 10}-${100000 + i}`,
  status: i === 0 ? "running" : "completed",
  trigger: i % 3 === 0 ? "knowledge_add" : "manual",
  created_at: `2026-07-${String(1 + (i % 28)).padStart(2, "0")}T12:00:00Z`,
  finished_at: i === 0 ? null : `2026-07-${String(1 + (i % 28)).padStart(2, "0")}T13:00:00Z`,
  doc_ids: [`doc-${i}`],
  doc_titles: [`Knowledge entry ${i} — fan-out rule`],
  repo_url: "https://github.com/org/big-set.git",
  model: "sonnet",
  eval_set_name: "big-set",
  eval_set_ref: "abc1234def5678",
  project_repo: "https://github.com/org/warehouse.git",
  project_ref: "main",
  build_fingerprint: "f1e2d3c4b5a69788",
  kb_doc_ids: [`doc-${i}`],
  summary: { total: 180, correct: 140 + (i % 30), partial: 2, error: 0 },
  progress: null,
  coverage: null,
  error: null,
  artifact_bytes: 1024 * 1024,
  artifacts_pruned: false,
  traces_pruned: false,
}));

const martModels = Array.from({ length: 32 }, (_, i) => ({
  name: `mart_${["revenue", "claims", "orders", "sessions"][i % 4]}_${String(i + 1).padStart(2, "0")}`,
  layer: "marts",
  covered: i % 7 !== 0,
  declared_by: i % 7 === 0 ? [] : [`t-${String((i % 24) + 1).padStart(3, "0")}_${["revenue", "claims", "orders", "sessions"][i % 4]}`],
  observed_by: i % 3 === 0 && i % 7 !== 0 ? [`t-${String((i % 24) + 1).padStart(3, "0")}_${["revenue", "claims", "orders", "sessions"][i % 4]}`] : [],
}));
runs[1].coverage = {
  declared: martModels.filter((model) => model.declared_by.length).map((model) => model.name),
  observed: martModels.filter((model) => model.observed_by.length).map((model) => model.name),
  observed_not_declared: [],
  per_task_observed: {},
  models_total: 80,
  models_covered: 70,
  pct: 87.5,
  marts_pct: 84.4,
  by_layer: { marts: { total: 32, covered: 27 }, staging: { total: 30, covered: 28 }, intermediate: { total: 18, covered: 15 } },
  models: martModels,
};

const history = Array.from({ length: 12 }, (_, i) => ({
  run_id: runs[Math.min(i + 1, runs.length - 1)].id,
  created_at: `2026-07-${String(2 + i * 2).padStart(2, "0")}T12:00:00Z`,
  trigger: i % 3 === 0 ? "knowledge_add" : "manual",
  eval_set_name: "big-set",
  eval_set_ref: "abc1234def5678",
  build_fingerprint: "f1e2d3c4b5a69788",
  tasks_total: 180,
  tasks_passed: 140 + ((i * 7) % 30) - (i === 8 ? 25 : 0),
  accuracy_pct: ((140 + ((i * 7) % 30) - (i === 8 ? 25 : 0)) / 180) * 100,
  coverage_pct: 60 + i,
  kb_doc_ids: [`doc-${i}`],
}));
const accuracy = {
  history,
  regressions: [
    {
      id: "reg-1",
      run_id: history[8].run_id,
      created_at: history[8].created_at,
      baseline_run_ids: [history[7].run_id],
      baseline_accuracy_pct: history[7].accuracy_pct,
      run_accuracy_pct: history[8].accuracy_pct,
      drop_pct: history[7].accuracy_pct - history[8].accuracy_pct,
      suspected_doc_ids: ["doc-8"],
      sole_change: true,
      flipped_tasks: [
        { task_id: "t-004_sessions", title: "Sessions rollup", verdict: "FAIL" },
        { task_id: "t-008_sessions", title: "Sessions by channel", verdict: "FAIL" },
      ],
      notified_at: null,
      recipients: [],
    },
  ],
  task_performance: tasks.slice(0, 70).map((task, i) => ({
    task_id: task.id,
    title: task.title,
    kind: task.kind,
    class: task.class,
    covers: task.covers,
    attempts: 8 + (i % 5),
    correct: i % 9 === 0 ? 3 : 7 + (i % 4),
    partial: i % 4,
    off: i % 9 === 0 ? 5 : i % 3,
    errors: i % 13 === 0 ? 1 : 0,
    pass_rate_pct: i % 9 === 0 ? 37.5 : 72 + (i % 29),
    avg_duration_s: 24 + i * 1.8,
    last_verdict: i % 9 === 0 ? "OFF" : "CORRECT",
    last_run_id: runs[1].id,
  })),
};

await page.route("**/api/evals/tasks", (r) =>
  r.fulfill({
    json: {
      name: "big-set",
      description: "180-task mocked set for scale UX",
      ref: "abc1234def5678",
      project_repo: "https://github.com/org/warehouse.git",
      build_fingerprint: "f1e2d3c4b5a69788",
      setup: {},
      tasks,
    },
  }));
await page.route("**/api/evals/runs", (r) =>
  r.fulfill({ json: { runs } }));
await page.route("**/api/evals/runs/*/progress", (r) =>
  r.fulfill({ json: { run_id: runs[0].id, status: "running", phase: "running", done: 63, total: 180, active: [{ task_id: tasks[63].id, title: tasks[63].title, phase: "agent", started_at: new Date().toISOString() }], started_at: new Date(Date.now() - 90000).toISOString(), elapsed_s: 90, updated_at: new Date().toISOString(), error: null } }));
await page.route("**/api/evals/runs/*/cancel", (r) => {
  runs[0].status = "cancelled";
  runs[0].finished_at = new Date().toISOString();
  r.fulfill({ json: { ...runs[0], tasks: [] } });
});
await page.route("**/api/evals/accuracy", (r) =>
  r.fulfill({ json: accuracy }));
await page.route("**/api/evals/config", (r) =>
  r.fulfill({
    json: {
      enabled: true,
      repo_url: "https://github.com/org/big-set.git",
      model: "sonnet",
      max_tasks: 0,
      prompt_preamble: "",
      connection: "warehouse_ro",
      autorun_on_knowledge_add: false,
      notify_emails: ["data-team@acme.com"],
    },
  }));
await page.route("**/api/evals/availability", (r) => r.fulfill({ json: { enabled: true, reason: "ok" } }));

await page.goto("http://localhost:3260/evals", { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
await page.screenshot({ path: "e2e-evals-redesign-scale-list.png", fullPage: false });

await page.getByRole("button", { name: "Stop run" }).first().click();
await page.waitForTimeout(700);
if (await page.getByRole("button", { name: "Stop run" }).count()) throw new Error("Stop control remained after cancellation");
await page.screenshot({ path: "e2e-evals-cancelled.png", fullPage: false });

// Test the search and task-type filters.
await page.fill('input[aria-label="search tasks"]', "claims");
await page.waitForTimeout(600);
await page.screenshot({ path: "e2e-evals-redesign-scale-search.png", fullPage: false });
await page.fill('input[aria-label="search tasks"]', "");

// Capture the card view.
await page.click('button[aria-label="card view"]');
await page.waitForTimeout(600);
await page.screenshot({ path: "e2e-evals-redesign-scale-cards.png", fullPage: false });

await page.goto("http://localhost:3260/evals/accuracy", { waitUntil: "networkidle" });
await page.waitForTimeout(1200);
await page.screenshot({ path: "e2e-accuracy-overview.png", fullPage: false });
await page.locator("text=Which tests protect each mart").scrollIntoViewIfNeeded();
await page.waitForTimeout(500);
await page.screenshot({ path: "e2e-accuracy-mart-coverage.png", fullPage: false });

await page.setViewportSize({ width: 390, height: 844 });
await page.goto("http://localhost:3260/evals", { waitUntil: "networkidle" });
await page.waitForTimeout(700);
await page.screenshot({ path: "e2e-evals-mobile.png", fullPage: false });
await page.goto("http://localhost:3260/evals/accuracy", { waitUntil: "networkidle" });
await page.waitForTimeout(700);
await page.screenshot({ path: "e2e-accuracy-mobile.png", fullPage: false });

await browser.close();
console.log("done");
