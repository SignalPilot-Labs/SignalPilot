// @vitest-environment node
import { describe, it, expect, vi, afterEach } from "vitest";
import { mkdtemp, readFile, access } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

afterEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
});

function stubLocalEnv(dir: string) {
  vi.stubEnv("WORKSPACES_MODE", "local");
  vi.stubEnv("WORKSPACES_API_URL", "http://localhost:3400");
  vi.stubEnv("SP_LOCAL_API_KEY", "test-key");
  vi.stubEnv("WORKSPACES_LOCAL_CHARTS_DIR", "/tmp/charts");
  vi.stubEnv("WORKSPACES_LOCAL_DBT_LINKS_DIR", "/tmp/dbt-links");
  vi.stubEnv("WORKSPACES_LOCAL_AGENT_RUNS_DIR", dir);
}

describe("saveAgentRun", () => {
  it("throws when env mode is cloud", async () => {
    vi.stubEnv("WORKSPACES_MODE", "cloud");
    vi.stubEnv("WORKSPACES_API_URL", "http://api");
    vi.stubEnv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "pk_test_xxx");
    vi.stubEnv("CLERK_SECRET_KEY", "sk_test_xxx");

    vi.resetModules();
    const { saveAgentRun } = await import("@/lib/agent-runs/save-run");
    const fd = new FormData();
    await expect(saveAgentRun(fd)).rejects.toThrow("saveAgentRun is only available in local mode");
  });

  it("returns { ok: false, error: 'Prompt is required.' } when prompt is not a string", async () => {
    const dir = await mkdtemp(join(tmpdir(), "save-run-"));
    stubLocalEnv(dir);
    vi.resetModules();
    const { saveAgentRun } = await import("@/lib/agent-runs/save-run");

    // No prompt field appended — formData.get("prompt") returns null
    const fd = new FormData();
    const result = await saveAgentRun(fd);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("Expected ok=false");
    expect(result.error).toBe("Prompt is required.");
  });

  it("returns { ok: false, error: 'Prompt is required.' } when prompt is empty string", async () => {
    const dir = await mkdtemp(join(tmpdir(), "save-run-"));
    stubLocalEnv(dir);
    vi.resetModules();
    const { saveAgentRun } = await import("@/lib/agent-runs/save-run");

    const fd = new FormData();
    fd.set("prompt", "");
    const result = await saveAgentRun(fd);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("Expected ok=false");
    expect(result.error).toBe("Prompt is required.");
  });

  it("returns { ok: false, error: 'Prompt is required.' } when prompt is whitespace-only", async () => {
    const dir = await mkdtemp(join(tmpdir(), "save-run-"));
    stubLocalEnv(dir);
    vi.resetModules();
    const { saveAgentRun } = await import("@/lib/agent-runs/save-run");

    const fd = new FormData();
    fd.set("prompt", "   \t\n  ");
    const result = await saveAgentRun(fd);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("Expected ok=false");
    expect(result.error).toBe("Prompt is required.");
  });

  it("returns { ok: false } with length error when prompt > 4000 chars", async () => {
    const dir = await mkdtemp(join(tmpdir(), "save-run-"));
    stubLocalEnv(dir);
    vi.resetModules();
    const { saveAgentRun } = await import("@/lib/agent-runs/save-run");

    const fd = new FormData();
    fd.set("prompt", "a".repeat(4001));
    const result = await saveAgentRun(fd);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("Expected ok=false");
    expect(result.error).toBe("Prompt must be 4000 characters or fewer.");
  });

  it("happy path writes manifest with status=pending and returns { ok: true, id }", async () => {
    const dir = await mkdtemp(join(tmpdir(), "save-run-"));
    stubLocalEnv(dir);
    vi.resetModules();
    const { saveAgentRun } = await import("@/lib/agent-runs/save-run");

    const fd = new FormData();
    fd.set("prompt", "Analyze the sales data and produce a summary report");
    const result = await saveAgentRun(fd);

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(`Expected ok=true, got: ${result.error}`);

    const { id } = result;

    // Manifest exists with correct shape
    const manifestPath = join(dir, `${id}.json`);
    const raw = await readFile(manifestPath, "utf-8");
    const manifest = JSON.parse(raw);

    expect(manifest.schemaVersion).toBe(1);
    expect(manifest.id).toBe(id);
    expect(manifest.prompt).toBe("Analyze the sales data and produce a summary report");
    expect(manifest.status).toBe("pending");
    expect(typeof manifest.createdAt).toBe("string");
  });

  it("tmp file does not survive: only <id>.json exists after success", async () => {
    const dir = await mkdtemp(join(tmpdir(), "save-run-"));
    stubLocalEnv(dir);
    vi.resetModules();
    const { saveAgentRun } = await import("@/lib/agent-runs/save-run");

    const fd = new FormData();
    fd.set("prompt", "Test prompt for atomic write verification");
    const result = await saveAgentRun(fd);

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(`Expected ok=true, got: ${result.error}`);

    const { id } = result;
    const finalPath = join(dir, `${id}.json`);
    const tmpPath = join(dir, `${id}.json.tmp`);

    // Final file exists
    await expect(readFile(finalPath, "utf-8")).resolves.toBeDefined();

    // Tmp file does not exist
    await expect(access(tmpPath)).rejects.toThrow();
  });

  it("surfaces unexpected fs error (mock rename to throw) and best-effort cleans tmp", async () => {
    const dir = await mkdtemp(join(tmpdir(), "save-run-"));
    stubLocalEnv(dir);

    // Mock fs/promises so rename throws
    vi.doMock("node:fs/promises", async () => {
      const actual = await vi.importActual<typeof import("node:fs/promises")>("node:fs/promises");
      return {
        ...actual,
        rename: vi.fn(async () => {
          throw new Error("MOCK_RENAME_FAILURE");
        }),
      };
    });

    vi.resetModules();
    const { saveAgentRun } = await import("@/lib/agent-runs/save-run");

    const fd = new FormData();
    fd.set("prompt", "This prompt triggers a rename failure");

    await expect(saveAgentRun(fd)).rejects.toThrow("MOCK_RENAME_FAILURE");
  });
});
