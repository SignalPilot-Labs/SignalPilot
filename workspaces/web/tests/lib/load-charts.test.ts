import { describe, it, expect, vi, afterEach } from "vitest";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ChartDefinitionV1 } from "@/lib/charts/types";

afterEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
});

function makeDefinition(overrides: Partial<ChartDefinitionV1> = {}): ChartDefinitionV1 {
  return {
    schemaVersion: 1,
    id: "aabbccdd-1234-4abc-8def-aabbccddeeff",
    name: "Test Chart",
    type: "bar",
    sql: "SELECT 1",
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

describe("loadChartDefinitions", () => {
  it("returns [] when the directory does not exist", async () => {
    const nonExistentDir = join(tmpdir(), "wsp-charts-nonexistent-" + Date.now());
    vi.stubEnv("WORKSPACES_LOCAL_CHARTS_DIR", nonExistentDir);
    vi.stubEnv("WORKSPACES_LOCAL_DBT_LINKS_DIR", "/tmp/dbt-links");
    vi.stubEnv("WORKSPACES_LOCAL_AGENT_RUNS_DIR", "/tmp/agent-runs");
    vi.stubEnv("WORKSPACES_MODE", "local");
    vi.stubEnv("WORKSPACES_API_URL", "http://localhost:3400");
    vi.stubEnv("SP_LOCAL_API_KEY", "test-key");

    vi.resetModules();
    const { loadChartDefinitions } = await import("@/lib/charts/load-charts");

    const result = await loadChartDefinitions();
    expect(result).toEqual([]);
  });

  it("returns entries sorted by createdAt descending", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-charts-"));
    vi.stubEnv("WORKSPACES_LOCAL_CHARTS_DIR", dir);
    vi.stubEnv("WORKSPACES_LOCAL_DBT_LINKS_DIR", "/tmp/dbt-links");
    vi.stubEnv("WORKSPACES_LOCAL_AGENT_RUNS_DIR", "/tmp/agent-runs");
    vi.stubEnv("WORKSPACES_MODE", "local");
    vi.stubEnv("WORKSPACES_API_URL", "http://localhost:3400");
    vi.stubEnv("SP_LOCAL_API_KEY", "test-key");

    const older = makeDefinition({
      id: "11111111-1111-4111-8111-111111111111",
      name: "Older Chart",
      createdAt: "2024-01-01T00:00:00.000Z",
    });
    const newer = makeDefinition({
      id: "22222222-2222-4222-8222-222222222222",
      name: "Newer Chart",
      createdAt: "2024-06-01T00:00:00.000Z",
    });

    await writeFile(join(dir, `${older.id}.json`), JSON.stringify(older), "utf-8");
    await writeFile(join(dir, `${newer.id}.json`), JSON.stringify(newer), "utf-8");

    vi.resetModules();
    const { loadChartDefinitions } = await import("@/lib/charts/load-charts");

    const result = await loadChartDefinitions();
    expect(result).toHaveLength(2);
    expect(result[0]?.id).toBe(newer.id);
    expect(result[1]?.id).toBe(older.id);
  });

  it("skips malformed and schemaVersion:2 files, warns, and returns only valid entries", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-charts-"));
    vi.stubEnv("WORKSPACES_LOCAL_CHARTS_DIR", dir);
    vi.stubEnv("WORKSPACES_LOCAL_DBT_LINKS_DIR", "/tmp/dbt-links");
    vi.stubEnv("WORKSPACES_LOCAL_AGENT_RUNS_DIR", "/tmp/agent-runs");
    vi.stubEnv("WORKSPACES_MODE", "local");
    vi.stubEnv("WORKSPACES_API_URL", "http://localhost:3400");
    vi.stubEnv("SP_LOCAL_API_KEY", "test-key");

    const valid = makeDefinition({
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      name: "Valid Chart",
    });
    const wrongVersion = { ...valid, id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", schemaVersion: 2 };
    const malformed = "{ not valid json ]]";

    await writeFile(join(dir, `${valid.id}.json`), JSON.stringify(valid), "utf-8");
    await writeFile(join(dir, `${wrongVersion.id}.json`), JSON.stringify(wrongVersion), "utf-8");
    await writeFile(join(dir, "cccccccc-cccc-4ccc-8ccc-cccccccccccc.json"), malformed, "utf-8");

    vi.resetModules();
    const { loadChartDefinitions } = await import("@/lib/charts/load-charts");

    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const result = await loadChartDefinitions();

    expect(result).toHaveLength(1);
    expect(result[0]?.id).toBe(valid.id);
    expect(warnSpy).toHaveBeenCalledTimes(2);

    warnSpy.mockRestore();
  });
});

describe("loadChartDefinition", () => {
  it("returns null for non-uuid id without touching disk", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-charts-"));
    vi.stubEnv("WORKSPACES_LOCAL_CHARTS_DIR", dir);
    vi.stubEnv("WORKSPACES_LOCAL_DBT_LINKS_DIR", "/tmp/dbt-links");
    vi.stubEnv("WORKSPACES_LOCAL_AGENT_RUNS_DIR", "/tmp/agent-runs");
    vi.stubEnv("WORKSPACES_MODE", "local");
    vi.stubEnv("WORKSPACES_API_URL", "http://localhost:3400");
    vi.stubEnv("SP_LOCAL_API_KEY", "test-key");

    vi.resetModules();
    const { loadChartDefinition } = await import("@/lib/charts/load-charts");

    const result = await loadChartDefinition("not-a-uuid");
    expect(result).toBeNull();

    // Also test another obviously invalid id
    const result2 = await loadChartDefinition("../../etc/passwd");
    expect(result2).toBeNull();
  });

  it("returns null for a missing file (ENOENT)", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-charts-"));
    vi.stubEnv("WORKSPACES_LOCAL_CHARTS_DIR", dir);
    vi.stubEnv("WORKSPACES_LOCAL_DBT_LINKS_DIR", "/tmp/dbt-links");
    vi.stubEnv("WORKSPACES_LOCAL_AGENT_RUNS_DIR", "/tmp/agent-runs");
    vi.stubEnv("WORKSPACES_MODE", "local");
    vi.stubEnv("WORKSPACES_API_URL", "http://localhost:3400");
    vi.stubEnv("SP_LOCAL_API_KEY", "test-key");

    vi.resetModules();
    const { loadChartDefinition } = await import("@/lib/charts/load-charts");

    const result = await loadChartDefinition("dddddddd-dddd-4ddd-8ddd-dddddddddddd");
    expect(result).toBeNull();
  });

  it("returns null for a file with wrong shape", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-charts-"));
    vi.stubEnv("WORKSPACES_LOCAL_CHARTS_DIR", dir);
    vi.stubEnv("WORKSPACES_LOCAL_DBT_LINKS_DIR", "/tmp/dbt-links");
    vi.stubEnv("WORKSPACES_LOCAL_AGENT_RUNS_DIR", "/tmp/agent-runs");
    vi.stubEnv("WORKSPACES_MODE", "local");
    vi.stubEnv("WORKSPACES_API_URL", "http://localhost:3400");
    vi.stubEnv("SP_LOCAL_API_KEY", "test-key");

    const id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
    await writeFile(join(dir, `${id}.json`), JSON.stringify({ wrong: "shape" }), "utf-8");

    vi.resetModules();
    const { loadChartDefinition } = await import("@/lib/charts/load-charts");

    const result = await loadChartDefinition(id);
    expect(result).toBeNull();
  });

  it("returns the definition for a valid file", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-charts-"));
    vi.stubEnv("WORKSPACES_LOCAL_CHARTS_DIR", dir);
    vi.stubEnv("WORKSPACES_LOCAL_DBT_LINKS_DIR", "/tmp/dbt-links");
    vi.stubEnv("WORKSPACES_LOCAL_AGENT_RUNS_DIR", "/tmp/agent-runs");
    vi.stubEnv("WORKSPACES_MODE", "local");
    vi.stubEnv("WORKSPACES_API_URL", "http://localhost:3400");
    vi.stubEnv("SP_LOCAL_API_KEY", "test-key");

    const def = makeDefinition({ id: "ffffffff-ffff-4fff-8fff-ffffffffffff" });
    await writeFile(join(dir, `${def.id}.json`), JSON.stringify(def), "utf-8");

    vi.resetModules();
    const { loadChartDefinition } = await import("@/lib/charts/load-charts");

    const result = await loadChartDefinition(def.id);
    expect(result).not.toBeNull();
    expect(result?.id).toBe(def.id);
    expect(result?.name).toBe(def.name);
    expect(result?.sql).toBe(def.sql);
  });
});
