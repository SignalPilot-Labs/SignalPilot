// @vitest-environment node
import { describe, it, expect, vi, afterEach } from "vitest";
import { mkdtemp, readFile, access, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import * as tar from "tar";
import { rm } from "node:fs/promises";

afterEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
});

function stubLocalEnv(dir: string) {
  vi.stubEnv("WORKSPACES_MODE", "local");
  vi.stubEnv("WORKSPACES_API_URL", "http://localhost:3400");
  vi.stubEnv("SP_LOCAL_API_KEY", "test-key");
  vi.stubEnv("WORKSPACES_LOCAL_CHARTS_DIR", "/tmp/charts");
  vi.stubEnv("WORKSPACES_LOCAL_DBT_LINKS_DIR", dir);
}

/**
 * Build an in-memory tar.gz Buffer from a list of { path, content } entries.
 * Returns a Blob so stream() is available (Node.js global Blob in node environment).
 */
async function buildTarGzBlob(
  files: Array<{ path: string; content: string }>,
): Promise<Blob> {
  // Write files to a temp source directory, then archive them.
  const srcDir = await mkdtemp(join(tmpdir(), "save-link-src-"));
  try {
    const fileNames: string[] = [];
    for (const f of files) {
      const fullPath = join(srcDir, f.path);
      await mkdir(join(fullPath, ".."), { recursive: true });
      const { writeFile } = await import("node:fs/promises");
      await writeFile(fullPath, f.content, "utf-8");
      fileNames.push(f.path);
    }

    const outPath = join(tmpdir(), `save-link-test-${Date.now()}.tar.gz`);
    await tar.c({ gzip: true, file: outPath, cwd: srcDir }, fileNames);
    const buf = await readFile(outPath);
    await rm(outPath, { force: true });

    return new Blob([buf], { type: "application/gzip" });
  } finally {
    await rm(srcDir, { recursive: true, force: true });
  }
}

/**
 * Build a File from a Blob with given name and type.
 * Uses Node.js global File (has stream/arrayBuffer).
 */
function blobToFile(blob: Blob, name: string, type: string): File {
  return new File([blob], name, { type });
}

describe("saveDbtLinkNativeUpload", () => {
  it("throws (cloud mode rejects) when env mode is cloud", async () => {
    vi.stubEnv("WORKSPACES_MODE", "cloud");
    vi.stubEnv("WORKSPACES_API_URL", "http://api");
    vi.stubEnv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "pk_test_xxx");
    vi.stubEnv("CLERK_SECRET_KEY", "sk_test_xxx");

    vi.resetModules();
    const { saveDbtLinkNativeUpload } = await import("@/lib/dbt-links/save-link");
    const fd = new FormData();
    await expect(saveDbtLinkNativeUpload(fd)).rejects.toThrow();
  });

  it("returns { ok: false } with name error when name is empty", async () => {
    const dir = await mkdtemp(join(tmpdir(), "save-link-"));
    stubLocalEnv(dir);
    vi.resetModules();
    const { saveDbtLinkNativeUpload } = await import("@/lib/dbt-links/save-link");

    const fd = new FormData();
    fd.set("name", "   ");
    const result = await saveDbtLinkNativeUpload(fd);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("Expected ok=false");
    expect(result.error.toLowerCase()).toMatch(/name/);
  });

  it("returns { ok: false, error: /file is required/ } when no file provided", async () => {
    const dir = await mkdtemp(join(tmpdir(), "save-link-"));
    stubLocalEnv(dir);
    vi.resetModules();
    const { saveDbtLinkNativeUpload } = await import("@/lib/dbt-links/save-link");

    const fd = new FormData();
    fd.set("name", "Test Project");
    // Deliberately omit "file"
    const result = await saveDbtLinkNativeUpload(fd);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("Expected ok=false");
    expect(result.error.toLowerCase()).toMatch(/file is required/);
  });

  it("returns { ok: false } when magic bytes are wrong (not a gzip archive)", async () => {
    const dir = await mkdtemp(join(tmpdir(), "save-link-"));
    stubLocalEnv(dir);
    vi.resetModules();
    const { saveDbtLinkNativeUpload } = await import("@/lib/dbt-links/save-link");

    // A file that starts with non-gzip bytes but has allowed content type
    const badContent = new Uint8Array([0x00, 0x00, 0x01, 0x02, 0x03]);
    const badFile = new File([badContent], "bad.tar.gz", { type: "application/gzip" });

    const fd = new FormData();
    fd.set("name", "Bad Project");
    fd.set("file", badFile);

    const result = await saveDbtLinkNativeUpload(fd);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("Expected ok=false");
    expect(result.error.toLowerCase()).toMatch(/gzip/);

    // Verify no <id>/ directory was created inside dir
    const { readdir } = await import("node:fs/promises");
    let entries: string[] = [];
    try {
      entries = await readdir(dir);
    } catch {
      entries = [];
    }
    // No UUID directories should be present
    const uuidDirs = entries.filter((e) =>
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(e),
    );
    expect(uuidDirs).toHaveLength(0);
  });

  it("happy path: valid tar.gz → { ok: true, id }; manifest and extracted files present", async () => {
    const dir = await mkdtemp(join(tmpdir(), "save-link-"));
    stubLocalEnv(dir);
    vi.resetModules();
    const { saveDbtLinkNativeUpload } = await import("@/lib/dbt-links/save-link");

    const blob = await buildTarGzBlob([
      { path: "models/model.sql", content: "SELECT 1" },
      { path: "dbt_project.yml", content: "name: test" },
    ]);
    const file = blobToFile(blob, "project.tar.gz", "application/gzip");

    const fd = new FormData();
    fd.set("name", "My dbt Project");
    fd.set("file", file);

    const result = await saveDbtLinkNativeUpload(fd);

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(`Expected ok=true, got: ${result.error}`);

    const { id } = result;

    // Manifest exists and has correct shape
    const manifestPath = join(dir, `${id}.json`);
    const raw = await readFile(manifestPath, "utf-8");
    const manifest = JSON.parse(raw);
    expect(manifest.schemaVersion).toBe(1);
    expect(manifest.id).toBe(id);
    expect(manifest.name).toBe("My dbt Project");
    expect(manifest.kind).toBe("native_upload");
    expect(manifest.relativePath).toBe(id);
    expect(typeof manifest.createdAt).toBe("string");

    // No .json.tmp artifact remains
    await expect(access(`${manifestPath}.tmp`)).rejects.toThrow();

    // Extracted contents exist
    const modelContent = await readFile(join(dir, id, "models", "model.sql"), "utf-8");
    expect(modelContent).toBe("SELECT 1");
    const dbtYml = await readFile(join(dir, id, "dbt_project.yml"), "utf-8");
    expect(dbtYml).toBe("name: test");
  });

  it("extractor failure cleans up: path-traversal tar → { ok: false }; no <id>/ dir left", async () => {
    const dir = await mkdtemp(join(tmpdir(), "save-link-"));
    stubLocalEnv(dir);
    vi.resetModules();
    const { saveDbtLinkNativeUpload } = await import("@/lib/dbt-links/save-link");

    // Build a tarball with a path-traversal entry.
    // Use a nested directory structure so ../evil.txt is valid relative path.
    const srcDir = await mkdtemp(join(tmpdir(), "traversal-src-"));
    const nestedDir = join(srcDir, "nested");
    await mkdir(nestedDir, { recursive: true });
    const { writeFile } = await import("node:fs/promises");
    await writeFile(join(srcDir, "evil.txt"), "evil");

    const outPath = join(tmpdir(), `traversal-${Date.now()}.tar.gz`);
    // cwd=nestedDir, entry="../evil.txt"
    await tar.c({ gzip: true, file: outPath, cwd: nestedDir }, ["../evil.txt"]);
    const tarBuf = await readFile(outPath);
    await rm(outPath, { force: true });
    await rm(srcDir, { recursive: true, force: true });

    const file = new File([tarBuf], "evil.tar.gz", { type: "application/gzip" });
    const fd = new FormData();
    fd.set("name", "Evil Project");
    fd.set("file", file);

    const result = await saveDbtLinkNativeUpload(fd);

    expect(result.ok).toBe(false);

    // Verify cleanup: no UUID directories remain
    const { readdir } = await import("node:fs/promises");
    let entries: string[] = [];
    try {
      entries = await readdir(dir);
    } catch {
      entries = [];
    }
    const uuidDirs = entries.filter((e) =>
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(e),
    );
    expect(uuidDirs).toHaveLength(0);

    // Verify no manifest was written
    const jsonFiles = entries.filter((e) => e.endsWith(".json"));
    expect(jsonFiles).toHaveLength(0);
  });
});
