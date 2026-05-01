import { describe, it, expect, vi, afterEach } from "vitest";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { DbtLinkV1 } from "@/lib/dbt-links/types";

afterEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
});

function makeLink(overrides: Partial<DbtLinkV1> = {}): DbtLinkV1 {
  return {
    schemaVersion: 1,
    id: "aabbccdd-1234-4abc-8def-aabbccddeeff",
    name: "Test Link",
    kind: "native_upload",
    createdAt: new Date().toISOString(),
    relativePath: "projects/test-project",
    ...overrides,
  };
}

function stubLocalEnv(dir: string) {
  vi.stubEnv("WORKSPACES_MODE", "local");
  vi.stubEnv("WORKSPACES_API_URL", "http://localhost:3400");
  vi.stubEnv("SP_LOCAL_API_KEY", "test-key");
  vi.stubEnv("WORKSPACES_LOCAL_CHARTS_DIR", "/tmp/charts");
  vi.stubEnv("WORKSPACES_LOCAL_DBT_LINKS_DIR", dir);
}

describe("loadDbtLinks", () => {
  it("returns [] when the directory is empty", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-dbt-links-"));
    stubLocalEnv(dir);
    vi.resetModules();
    const { loadDbtLinks } = await import("@/lib/dbt-links/load-links");
    const result = await loadDbtLinks();
    expect(result).toEqual([]);
  });

  it("returns [] when the directory does not exist (ENOENT)", async () => {
    const nonExistentDir = join(tmpdir(), "wsp-dbt-links-nonexistent-" + Date.now());
    stubLocalEnv(nonExistentDir);
    vi.resetModules();
    const { loadDbtLinks } = await import("@/lib/dbt-links/load-links");
    const result = await loadDbtLinks();
    expect(result).toEqual([]);
  });

  it("filters out .json.tmp files", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-dbt-links-"));
    stubLocalEnv(dir);

    const link = makeLink({ id: "11111111-1111-4111-8111-111111111111", name: "Real Link" });
    await writeFile(join(dir, `${link.id}.json`), JSON.stringify(link), "utf-8");
    await writeFile(join(dir, `${link.id}.json.tmp`), JSON.stringify(link), "utf-8");

    vi.resetModules();
    const { loadDbtLinks } = await import("@/lib/dbt-links/load-links");
    const result = await loadDbtLinks();
    expect(result).toHaveLength(1);
    expect(result[0]?.id).toBe(link.id);
  });

  it("skips malformed JSON, warns, and returns only valid siblings", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-dbt-links-"));
    stubLocalEnv(dir);

    const valid = makeLink({ id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", name: "Valid Link" });
    await writeFile(join(dir, `${valid.id}.json`), JSON.stringify(valid), "utf-8");
    await writeFile(join(dir, "bad.json"), "{ not valid json ]]", "utf-8");

    vi.resetModules();
    const { loadDbtLinks } = await import("@/lib/dbt-links/load-links");
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const result = await loadDbtLinks();

    expect(result).toHaveLength(1);
    expect(result[0]?.id).toBe(valid.id);
    expect(warnSpy).toHaveBeenCalledTimes(1);
    warnSpy.mockRestore();
  });

  it("rejects files with schemaVersion !== 1, warns, and returns valid siblings", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-dbt-links-"));
    stubLocalEnv(dir);

    const valid = makeLink({ id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", name: "Valid Link" });
    const wrongVersion = { ...valid, id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", schemaVersion: 2 };
    await writeFile(join(dir, `${valid.id}.json`), JSON.stringify(valid), "utf-8");
    await writeFile(join(dir, `${wrongVersion.id}.json`), JSON.stringify(wrongVersion), "utf-8");

    vi.resetModules();
    const { loadDbtLinks } = await import("@/lib/dbt-links/load-links");
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const result = await loadDbtLinks();

    expect(result).toHaveLength(1);
    expect(result[0]?.id).toBe(valid.id);
    expect(warnSpy).toHaveBeenCalledTimes(1);
    warnSpy.mockRestore();
  });

  it("rejects files with unknown kind, warns, and returns valid siblings", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-dbt-links-"));
    stubLocalEnv(dir);

    const valid = makeLink({ id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd", name: "Valid Link" });
    const unknownKind = { ...valid, id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee", kind: "unknown_kind" };
    await writeFile(join(dir, `${valid.id}.json`), JSON.stringify(valid), "utf-8");
    await writeFile(join(dir, `${unknownKind.id}.json`), JSON.stringify(unknownKind), "utf-8");

    vi.resetModules();
    const { loadDbtLinks } = await import("@/lib/dbt-links/load-links");
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const result = await loadDbtLinks();

    expect(result).toHaveLength(1);
    expect(result[0]?.id).toBe(valid.id);
    expect(warnSpy).toHaveBeenCalledTimes(1);
    warnSpy.mockRestore();
  });

  it("sorts results descending by createdAt", async () => {
    const dir = await mkdtemp(join(tmpdir(), "wsp-dbt-links-"));
    stubLocalEnv(dir);

    const older = makeLink({
      id: "11111111-1111-4111-8111-111111111111",
      name: "Older Link",
      createdAt: "2024-01-01T00:00:00.000Z",
    });
    const newer = makeLink({
      id: "22222222-2222-4222-8222-222222222222",
      name: "Newer Link",
      createdAt: "2024-06-01T00:00:00.000Z",
    });

    await writeFile(join(dir, `${older.id}.json`), JSON.stringify(older), "utf-8");
    await writeFile(join(dir, `${newer.id}.json`), JSON.stringify(newer), "utf-8");

    vi.resetModules();
    const { loadDbtLinks } = await import("@/lib/dbt-links/load-links");
    const result = await loadDbtLinks();

    expect(result).toHaveLength(2);
    expect(result[0]?.id).toBe(newer.id);
    expect(result[1]?.id).toBe(older.id);
  });

  it("throws when env mode is cloud", async () => {
    vi.stubEnv("WORKSPACES_MODE", "cloud");
    vi.stubEnv("WORKSPACES_API_URL", "http://api");
    vi.stubEnv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "pk_test_xxx");
    vi.stubEnv("CLERK_SECRET_KEY", "sk_test_xxx");

    vi.resetModules();
    const { loadDbtLinks } = await import("@/lib/dbt-links/load-links");
    await expect(loadDbtLinks()).rejects.toThrow("local mode");
  });
});
