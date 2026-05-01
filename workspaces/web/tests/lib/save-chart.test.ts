import { describe, it, expect, vi, afterEach } from "vitest";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ChartDefinitionV1 } from "@/lib/charts/types";

afterEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
});

describe("saveChartDefinition", () => {
  it("happy path: writes a valid ChartDefinitionV1 JSON file on disk", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-charts-"));
    vi.stubEnv("WORKSPACES_LOCAL_CHARTS_DIR", dir);
    vi.stubEnv("WORKSPACES_LOCAL_DBT_LINKS_DIR", "/tmp/dbt-links");
    vi.stubEnv("WORKSPACES_MODE", "local");
    vi.stubEnv("WORKSPACES_API_URL", "http://localhost:3400");
    vi.stubEnv("SP_LOCAL_API_KEY", "test-key");

    vi.resetModules();
    const { saveChartDefinition } = await import("@/lib/charts/save-chart");

    const result = await saveChartDefinition({
      name: "My Chart",
      type: "bar",
      sql: "SELECT 1",
    });

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("Expected ok=true");

    const filePath = join(dir, `${result.id}.json`);
    const raw = await readFile(filePath, "utf-8");
    const parsed: ChartDefinitionV1 = JSON.parse(raw);

    expect(parsed.schemaVersion).toBe(1);
    expect(parsed.id).toBe(result.id);
    expect(parsed.name).toBe("My Chart");
    expect(parsed.type).toBe("bar");
    expect(parsed.sql).toBe("SELECT 1");
    // id is uuid v4 shape
    expect(parsed.id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
    // createdAt parses as a valid Date
    const date = new Date(parsed.createdAt);
    expect(isNaN(date.getTime())).toBe(false);
  });

  it("rejects empty/whitespace name without writing a file", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-charts-"));
    vi.stubEnv("WORKSPACES_LOCAL_CHARTS_DIR", dir);
    vi.stubEnv("WORKSPACES_LOCAL_DBT_LINKS_DIR", "/tmp/dbt-links");
    vi.stubEnv("WORKSPACES_MODE", "local");
    vi.stubEnv("WORKSPACES_API_URL", "http://localhost:3400");
    vi.stubEnv("SP_LOCAL_API_KEY", "test-key");

    vi.resetModules();
    const { saveChartDefinition } = await import("@/lib/charts/save-chart");

    const result = await saveChartDefinition({
      name: "   ",
      type: "line",
      sql: "SELECT 1",
    });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("Expected ok=false");
    expect(result.error).toBeTruthy();
  });

  it("rejects an unknown chart type (cast bypass)", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-charts-"));
    vi.stubEnv("WORKSPACES_LOCAL_CHARTS_DIR", dir);
    vi.stubEnv("WORKSPACES_LOCAL_DBT_LINKS_DIR", "/tmp/dbt-links");
    vi.stubEnv("WORKSPACES_MODE", "local");
    vi.stubEnv("WORKSPACES_API_URL", "http://localhost:3400");
    vi.stubEnv("SP_LOCAL_API_KEY", "test-key");

    vi.resetModules();
    const { saveChartDefinition } = await import("@/lib/charts/save-chart");

    // Force an invalid type via cast bypass
    const result = await saveChartDefinition({
      name: "Chart",
      type: "pie" as unknown as "bar",
      sql: "SELECT 1",
    });

    expect(result.ok).toBe(false);
  });

  it("throws when mode=cloud (defense-in-depth guard)", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-charts-"));
    vi.stubEnv("WORKSPACES_LOCAL_CHARTS_DIR", dir);
    vi.stubEnv("WORKSPACES_MODE", "cloud");
    vi.stubEnv("WORKSPACES_API_URL", "http://api");
    vi.stubEnv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "pk_test_xxx");
    vi.stubEnv("CLERK_SECRET_KEY", "sk_test_xxx");

    vi.resetModules();
    const { saveChartDefinition } = await import("@/lib/charts/save-chart");

    await expect(
      saveChartDefinition({ name: "Chart", type: "bar", sql: "SELECT 1" }),
    ).rejects.toThrow();
  });
});
