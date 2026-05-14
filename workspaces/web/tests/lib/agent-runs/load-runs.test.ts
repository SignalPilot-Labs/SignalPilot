import { describe, it, expect, vi, afterEach } from "vitest";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { AgentRunV1 } from "@/lib/agent-runs/types";

afterEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
});

function makeRun(overrides: Partial<AgentRunV1> = {}): AgentRunV1 {
  return {
    schemaVersion: 1,
    id: "aabbccdd-1234-4abc-8def-aabbccddeeff",
    prompt: "Analyze the sales data and generate a report",
    status: "pending",
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

function stubLocalEnv(dir: string) {
  vi.stubEnv("WORKSPACES_MODE", "local");
  vi.stubEnv("WORKSPACES_API_URL", "http://localhost:3400");
  vi.stubEnv("SP_LOCAL_API_KEY", "test-key");
  vi.stubEnv("WORKSPACES_LOCAL_CHARTS_DIR", "/tmp/charts");
  vi.stubEnv("WORKSPACES_LOCAL_DBT_LINKS_DIR", "/tmp/dbt-links");
  vi.stubEnv("WORKSPACES_LOCAL_AGENT_RUNS_DIR", dir);
}

describe("loadAgentRuns", () => {
  it("throws when env mode is cloud", async () => {
    vi.stubEnv("WORKSPACES_MODE", "cloud");
    vi.stubEnv("WORKSPACES_API_URL", "http://api");
    vi.stubEnv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "pk_test_xxx");
    vi.stubEnv("CLERK_SECRET_KEY", "sk_test_xxx");

    vi.resetModules();
    const { loadAgentRuns } = await import("@/lib/agent-runs/load-runs");
    await expect(loadAgentRuns()).rejects.toThrow("loadAgentRuns is only available in local mode");
  });

  it("returns [] when directory does not exist (ENOENT)", async () => {
    const nonExistentDir = join(tmpdir(), "wsp-agent-runs-nonexistent-" + Date.now());
    stubLocalEnv(nonExistentDir);
    vi.resetModules();
    const { loadAgentRuns } = await import("@/lib/agent-runs/load-runs");
    const result = await loadAgentRuns();
    expect(result).toEqual([]);
  });

  it("reads a valid manifest", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-agent-runs-"));
    stubLocalEnv(dir);

    const run = makeRun({ id: "11111111-1111-4111-8111-111111111111" });
    await writeFile(join(dir, `${run.id}.json`), JSON.stringify(run), "utf-8");

    vi.resetModules();
    const { loadAgentRuns } = await import("@/lib/agent-runs/load-runs");
    const result = await loadAgentRuns();

    expect(result).toHaveLength(1);
    expect(result[0]?.id).toBe(run.id);
    expect(result[0]?.prompt).toBe(run.prompt);
    expect(result[0]?.status).toBe("pending");
  });

  it("skips *.json.tmp files", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-agent-runs-"));
    stubLocalEnv(dir);

    const run = makeRun({ id: "11111111-1111-4111-8111-111111111111" });
    await writeFile(join(dir, `${run.id}.json`), JSON.stringify(run), "utf-8");
    await writeFile(join(dir, `${run.id}.json.tmp`), JSON.stringify(run), "utf-8");

    vi.resetModules();
    const { loadAgentRuns } = await import("@/lib/agent-runs/load-runs");
    const result = await loadAgentRuns();
    expect(result).toHaveLength(1);
    expect(result[0]?.id).toBe(run.id);
  });

  it("skips malformed JSON with console.warn and returns valid siblings", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-agent-runs-"));
    stubLocalEnv(dir);

    const valid = makeRun({ id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" });
    await writeFile(join(dir, `${valid.id}.json`), JSON.stringify(valid), "utf-8");
    await writeFile(join(dir, "bad.json"), "{ not valid json ]]", "utf-8");

    vi.resetModules();
    const { loadAgentRuns } = await import("@/lib/agent-runs/load-runs");
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const result = await loadAgentRuns();

    expect(result).toHaveLength(1);
    expect(result[0]?.id).toBe(valid.id);
    expect(warnSpy).toHaveBeenCalledTimes(1);
    warnSpy.mockRestore();
  });

  it("skips wrong schemaVersion with console.warn and returns valid siblings", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-agent-runs-"));
    stubLocalEnv(dir);

    const valid = makeRun({ id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" });
    const wrongVersion = { ...valid, id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", schemaVersion: 2 };
    await writeFile(join(dir, `${valid.id}.json`), JSON.stringify(valid), "utf-8");
    await writeFile(join(dir, `${wrongVersion.id}.json`), JSON.stringify(wrongVersion), "utf-8");

    vi.resetModules();
    const { loadAgentRuns } = await import("@/lib/agent-runs/load-runs");
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const result = await loadAgentRuns();

    expect(result).toHaveLength(1);
    expect(result[0]?.id).toBe(valid.id);
    expect(warnSpy).toHaveBeenCalledTimes(1);
    warnSpy.mockRestore();
  });

  it("skips unknown status with console.warn and returns valid siblings", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-agent-runs-"));
    stubLocalEnv(dir);

    const valid = makeRun({ id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd" });
    const unknownStatus = {
      ...valid,
      id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
      status: "unknown_status",
    };
    await writeFile(join(dir, `${valid.id}.json`), JSON.stringify(valid), "utf-8");
    await writeFile(join(dir, `${unknownStatus.id}.json`), JSON.stringify(unknownStatus), "utf-8");

    vi.resetModules();
    const { loadAgentRuns } = await import("@/lib/agent-runs/load-runs");
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const result = await loadAgentRuns();

    expect(result).toHaveLength(1);
    expect(result[0]?.id).toBe(valid.id);
    expect(warnSpy).toHaveBeenCalledTimes(1);
    warnSpy.mockRestore();
  });

  it("sorts results descending by createdAt", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-agent-runs-"));
    stubLocalEnv(dir);

    const older = makeRun({
      id: "11111111-1111-4111-8111-111111111111",
      createdAt: "2024-01-01T00:00:00.000Z",
    });
    const newer = makeRun({
      id: "22222222-2222-4222-8222-222222222222",
      createdAt: "2024-06-01T00:00:00.000Z",
    });

    await writeFile(join(dir, `${older.id}.json`), JSON.stringify(older), "utf-8");
    await writeFile(join(dir, `${newer.id}.json`), JSON.stringify(newer), "utf-8");

    vi.resetModules();
    const { loadAgentRuns } = await import("@/lib/agent-runs/load-runs");
    const result = await loadAgentRuns();

    expect(result).toHaveLength(2);
    expect(result[0]?.id).toBe(newer.id);
    expect(result[1]?.id).toBe(older.id);
  });
});

describe("loadAgentRun", () => {
  it("returns null for non-UUID ids (UUID-regex guard)", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-agent-runs-"));
    stubLocalEnv(dir);
    vi.resetModules();
    const { loadAgentRun } = await import("@/lib/agent-runs/load-runs");

    expect(await loadAgentRun("../etc/passwd")).toBeNull();
    expect(await loadAgentRun("not-a-uuid")).toBeNull();
    expect(await loadAgentRun("")).toBeNull();
  });

  it("returns null for ENOENT (missing file)", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-agent-runs-"));
    stubLocalEnv(dir);
    vi.resetModules();
    const { loadAgentRun } = await import("@/lib/agent-runs/load-runs");

    const result = await loadAgentRun("dddddddd-dddd-4ddd-8ddd-dddddddddddd");
    expect(result).toBeNull();
  });

  it("returns parsed run on happy path", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-agent-runs-"));
    stubLocalEnv(dir);

    const id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    const run = makeRun({ id, prompt: "My test prompt" });
    await writeFile(join(dir, `${id}.json`), JSON.stringify(run), "utf-8");

    vi.resetModules();
    const { loadAgentRun } = await import("@/lib/agent-runs/load-runs");
    const result = await loadAgentRun(id);

    expect(result).not.toBeNull();
    expect(result?.id).toBe(id);
    expect(result?.prompt).toBe("My test prompt");
    expect(result?.status).toBe("pending");
  });

  it("throws when mode is cloud", async () => {
    vi.stubEnv("WORKSPACES_MODE", "cloud");
    vi.stubEnv("WORKSPACES_API_URL", "http://api");
    vi.stubEnv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "pk_test_xxx");
    vi.stubEnv("CLERK_SECRET_KEY", "sk_test_xxx");

    vi.resetModules();
    const { loadAgentRun } = await import("@/lib/agent-runs/load-runs");
    await expect(loadAgentRun("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")).rejects.toThrow(
      "loadAgentRun is only available in local mode",
    );
  });
});
