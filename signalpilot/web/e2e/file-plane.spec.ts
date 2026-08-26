import { test, expect, type APIRequestContext } from "@playwright/test";

/**
 * Workspace file plane — multi-cycle CRUD through the real gateway Files API.
 *
 * Every operation must be a durable revision: create, overwrite, rename
 * (copy+delete), delete, and repeated cycles of the same. Listing must always
 * reflect the store, never a stale cache.
 */

const GATEWAY = "http://localhost:3300";
const CYCLES = 3;

let apiKey = "";
let projectId = "";

async function api(request: APIRequestContext, method: "get" | "post" | "put" | "delete", path: string, body?: unknown, raw?: string) {
  const opts: Record<string, unknown> = {
    headers: {
      Authorization: `Bearer ${apiKey}`,
      ...(raw !== undefined ? { "Content-Type": "application/octet-stream" } : { "Content-Type": "application/json" }),
    },
  };
  if (raw !== undefined) opts.data = raw;
  else if (body !== undefined) opts.data = body;
  return request[method](`${GATEWAY}${path}`, opts);
}

async function listPaths(request: APIRequestContext): Promise<string[]> {
  const resp = await api(request, "post", `/api/workspace-projects/${projectId}/files:list`, { branch: "main" });
  expect(resp.ok(), `files:list ${resp.status()}`).toBe(true);
  const files = ((await resp.json()) as { files?: Array<{ path: string }> }).files ?? [];
  return files.map((f) => f.path);
}

test.describe.serial("File plane CRUD cycles", () => {
  test.beforeAll(async ({ request }) => {
    const key = await request.get("http://localhost:3200/api/local-key");
    apiKey = ((await key.json()) as { key?: string }).key ?? "";
    const resp = await request.post(`${GATEWAY}/api/workspace-projects`, {
      headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
      data: { name: `e2e-files-${Date.now().toString(36)}`, display_name: "E2E file plane", source: "managed", tags: ["e2e"] },
    });
    expect(resp.ok()).toBe(true);
    projectId = ((await resp.json()) as { id: string }).id;
  });

  test.afterAll(async ({ request }) => {
    if (projectId) {
      await request.delete(`${GATEWAY}/api/workspace-projects/${projectId}`, {
        headers: { Authorization: `Bearer ${apiKey}` },
      }).catch(() => {});
    }
  });

  test("create → read → overwrite → read cycles", async ({ request }) => {
    for (let cycle = 1; cycle <= CYCLES; cycle++) {
      const path = `cycle_${cycle}/data.txt`;
      const v1 = `cycle ${cycle} v1`;
      const v2 = `cycle ${cycle} v2 — overwritten`;

      const put1 = await api(request, "put", `/api/workspace-projects/${projectId}/files/${path}?branch=main`, undefined, v1);
      expect(put1.ok(), `put v1 c${cycle}: ${put1.status()}`).toBe(true);

      const get1 = await api(request, "get", `/api/workspace-projects/${projectId}/files/${path}?branch=main`);
      expect(await get1.text()).toBe(v1);

      const put2 = await api(request, "put", `/api/workspace-projects/${projectId}/files/${path}?branch=main`, undefined, v2);
      expect(put2.ok()).toBe(true);

      const get2 = await api(request, "get", `/api/workspace-projects/${projectId}/files/${path}?branch=main`);
      expect(await get2.text()).toBe(v2);

      expect(await listPaths(request)).toContain(path);
    }
  });

  test("batch commit + move + delete keep the listing truthful", async ({ request }) => {
    // Batch create
    const b64 = (s: string) => Buffer.from(s).toString("base64");
    const head = await api(request, "get", `/api/workspace-projects/${projectId}/revisions?branch=main&limit=1`);
    const revs = (await head.json()) as { revisions?: Array<{ revision: number }> };
    const base = revs.revisions?.[0]?.revision ?? null;

    const batch = await api(request, "post", `/api/workspace-projects/${projectId}/files:batch`, {
      branch: "main",
      base_revision: base,
      upserts: [
        { path: "batch/a.txt", content_b64: b64("alpha") },
        { path: "batch/b.txt", content_b64: b64("beta") },
      ],
      message: "e2e batch",
    });
    expect(batch.ok(), `batch ${batch.status()}`).toBe(true);

    let paths = await listPaths(request);
    expect(paths).toContain("batch/a.txt");
    expect(paths).toContain("batch/b.txt");

    // Move
    const move = await api(request, "post", `/api/workspace-projects/${projectId}/files:move`, {
      branch: "main",
      source: "batch/a.txt",
      destination: "batch/renamed.txt",
    });
    expect(move.ok(), `move ${move.status()}`).toBe(true);
    paths = await listPaths(request);
    expect(paths).toContain("batch/renamed.txt");
    expect(paths).not.toContain("batch/a.txt");

    // Delete
    const del = await api(request, "delete", `/api/workspace-projects/${projectId}/files/batch/b.txt?branch=main`);
    expect(del.ok(), `delete ${del.status()}`).toBe(true);
    paths = await listPaths(request);
    expect(paths).not.toContain("batch/b.txt");

    // Deleted file reads as gone
    const gone = await api(request, "get", `/api/workspace-projects/${projectId}/files/batch/b.txt?branch=main`);
    expect(gone.status()).toBe(404);
  });

  test("history: earlier revisions stay readable", async ({ request }) => {
    const revsResp = await api(request, "get", `/api/workspace-projects/${projectId}/revisions?branch=main&limit=50`);
    const revs = ((await revsResp.json()) as { revisions?: Array<{ revision: number }> }).revisions ?? [];
    expect(revs.length).toBeGreaterThan(3);

    // cycle_1/data.txt was overwritten; some earlier revision must still hold v1.
    let sawV1 = false;
    for (const r of revs) {
      const at = await api(
        request, "get",
        `/api/workspace-projects/${projectId}/files/cycle_1/data.txt?branch=main&revision=${r.revision}`,
      );
      if (at.ok() && (await at.text()) === "cycle 1 v1") { sawV1 = true; break; }
    }
    expect(sawV1, "an earlier revision should still contain v1").toBe(true);
  });
});
