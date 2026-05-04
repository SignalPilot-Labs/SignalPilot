import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtemp, writeFile, symlink, rm, readFile, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import * as tar from "tar";
import { createGunzip } from "node:zlib";
import { Readable } from "node:stream";

// Dynamically import so we can access the exported constants.
async function getExtractor() {
  return import("@/lib/dbt-links/extract-tarball");
}

/**
 * Build a gzipped tarball from `sourceDir` and return it as a Buffer.
 */
async function buildTarGzBuffer(
  sourceDir: string,
  files: string[],
  options?: Parameters<typeof tar.c>[0],
): Promise<Buffer> {
  const outPath = join(tmpdir(), `extract-test-${Date.now()}.tar.gz`);
  await tar.c({ gzip: true, file: outPath, cwd: sourceDir, ...options }, files);
  const buf = await readFile(outPath);
  await rm(outPath, { force: true });
  return buf;
}

/**
 * Returns a Readable (raw tar stream, no gzip) from a tar.gz Buffer.
 */
function gunzippedReadable(tarGzBuf: Buffer): Readable {
  const input = Readable.from(tarGzBuf);
  return input.pipe(createGunzip());
}

let srcDir: string;
let destDir: string;

beforeEach(async () => {
  srcDir = await mkdtemp(join(tmpdir(), "extract-src-"));
  destDir = await mkdtemp(join(tmpdir(), "extract-dest-"));
  // Remove destDir so extractTarballToDir creates it itself.
  await rm(destDir, { recursive: true, force: true });
});

afterEach(async () => {
  await rm(srcDir, { recursive: true, force: true }).catch(() => {});
  await rm(destDir, { recursive: true, force: true }).catch(() => {});
});

describe("extractTarballToDir", () => {
  it("happy path: extracts two files; entryCount === 2; contents match", async () => {
    await writeFile(join(srcDir, "a.txt"), "hello");
    await writeFile(join(srcDir, "b.txt"), "world");

    const buf = await buildTarGzBuffer(srcDir, ["a.txt", "b.txt"]);
    const { extractTarballToDir } = await getExtractor();
    const result = await extractTarballToDir({
      source: gunzippedReadable(buf),
      destDir,
    });

    expect(result.entryCount).toBe(2);
    expect(await readFile(join(destDir, "a.txt"), "utf-8")).toBe("hello");
    expect(await readFile(join(destDir, "b.txt"), "utf-8")).toBe("world");
    expect(result.totalBytes).toBe(10); // "hello" + "world"
  });

  it("path traversal blocked: ../evil.txt throws 'tarball entry escapes destination'", async () => {
    // We need to craft a tarball with a path-traversal entry.
    // Build an archive, then create a new one using WriteEntry to add an evil path.
    // Easiest: create a normal file in src, tar it, then use the Pack API.
    // Instead, build a tarball with `portable: true` and rely on the fact that
    // tar.c does NOT rewrite paths — we write to a different cwd to get `../`.
    const parentDir = join(srcDir, "nested");
    const { mkdir: mkdirNative } = await import("node:fs/promises");
    await mkdirNative(parentDir);
    await writeFile(join(srcDir, "evil.txt"), "pwned");

    // cwd is parentDir, file is ../evil.txt
    const buf = await buildTarGzBuffer(parentDir, ["../evil.txt"]);
    const { extractTarballToDir } = await getExtractor();

    await expect(
      extractTarballToDir({ source: gunzippedReadable(buf), destDir }),
    ).rejects.toThrow("tarball entry escapes destination");
  });

  it("absolute path blocked: /etc/passwd-style entry throws", async () => {
    // We cannot easily create absolute paths with tar.c without --absolute-names.
    // Use the low-level Pack approach: create an archive that contains an
    // absolute-path entry by building it with the `preservePaths` option.
    // tar.c with cwd=/ and file '/etc/passwd' style paths needs real paths.
    // Simpler: create the file at srcDir/etc/passwd and tar with preservePaths.
    const { mkdir: mkdirNative } = await import("node:fs/promises");
    await mkdirNative(join(srcDir, "etc"), { recursive: true });
    await writeFile(join(srcDir, "etc", "passwd"), "root:x:0:0");

    // preservePaths includes the srcDir path in the archive (absolute-ish).
    // Actually, we need the entry path to start with `/`.
    // Build manually: use Pack stream with an entry that has an absolute path header.
    // The easiest way is to build a raw (not gzipped) tar buffer with a crafted header.

    // We'll use the tar.Pack + process.cwd trick: create entries with absolute paths
    // by temporarily writing a file at an absolute path (which we own).
    // Actually, the cleanest approach: construct a minimal tar buffer manually.
    // A tar entry: 512-byte header + data + padding.
    // Header fields (all in 512 bytes, old POSIX format):
    //   offset 0: name (100 bytes, null-terminated)
    //   offset 100: mode (8 bytes, octal string)
    //   ...
    //   offset 124: size (12 bytes, octal string)
    //   ...
    //   offset 148: checksum (8 bytes)
    //   offset 156: type flag (1 byte)
    //   ...
    // We build a synthetic archive buffer with "/evil.txt" as the path.

    const header = Buffer.alloc(512, 0);
    // name: "/evil.txt"
    header.write("/evil.txt", 0, "ascii");
    // mode: "0000644\0"
    header.write("0000644\0", 100, "ascii");
    // uid: "0000000\0"
    header.write("0000000\0", 108, "ascii");
    // gid: "0000000\0"
    header.write("0000000\0", 116, "ascii");
    // size: "00000000005\0" (5 bytes)
    header.write("00000000005\0", 124, "ascii");
    // mtime: "00000000000\0"
    header.write("00000000000\0", 136, "ascii");
    // typeflag: '0' (regular file)
    header.write("0", 156, "ascii");
    // magic: "ustar\0"
    header.write("ustar\0", 257, "ascii");
    // version: "00"
    header.write("00", 263, "ascii");

    // Compute checksum (sum of all bytes with checksum field as spaces)
    header.fill(0x20, 148, 156); // checksum field = spaces for calculation
    let checksum = 0;
    for (let i = 0; i < 512; i++) checksum += header[i]!;
    header.write(checksum.toString(8).padStart(6, "0") + "\0 ", 148, "ascii");

    // Data block: "pwned" padded to 512 bytes
    const data = Buffer.alloc(512, 0);
    data.write("pwned", 0, "ascii");

    // Two null blocks to mark end of archive
    const eof = Buffer.alloc(1024, 0);

    const rawTar = Buffer.concat([header, data, eof]);

    // Gzip it
    const { promisify } = await import("node:util");
    const { gzip } = await import("node:zlib");
    const gzipAsync = promisify(gzip);
    const tarGz = await gzipAsync(rawTar);

    const { extractTarballToDir } = await getExtractor();

    await expect(
      extractTarballToDir({ source: gunzippedReadable(tarGz), destDir }),
    ).rejects.toThrow("tarball entry escapes destination");
  });

  it("symlink blocked: SymbolicLink entry throws 'tarball contains disallowed entry type'", async () => {
    await writeFile(join(srcDir, "real.txt"), "real content");
    await symlink("real.txt", join(srcDir, "link.txt"));

    const buf = await buildTarGzBuffer(srcDir, ["real.txt", "link.txt"]);
    const { extractTarballToDir } = await getExtractor();

    await expect(
      extractTarballToDir({ source: gunzippedReadable(buf), destDir }),
    ).rejects.toThrow("tarball contains disallowed entry type");
  });

  it("size cap enforced: entry whose size exceeds MAX_TOTAL_BYTES throws", async () => {
    const { MAX_TOTAL_BYTES } = await getExtractor();
    // Write a file slightly over the cap.
    const bigContent = Buffer.alloc(MAX_TOTAL_BYTES + 1, 0x41); // 'A' * (50MiB + 1)
    await writeFile(join(srcDir, "big.bin"), bigContent);

    const buf = await buildTarGzBuffer(srcDir, ["big.bin"]);
    const { extractTarballToDir } = await getExtractor();

    await expect(
      extractTarballToDir({ source: gunzippedReadable(buf), destDir }),
    ).rejects.toThrow("tarball exceeds size cap");
  }, 30_000);

  it("count cap enforced: > MAX_ENTRY_COUNT zero-byte files throw", async () => {
    const { MAX_ENTRY_COUNT } = await getExtractor();
    // Create MAX_ENTRY_COUNT + 1 zero-byte files.
    const count = MAX_ENTRY_COUNT + 1;
    const fileNames: string[] = [];
    for (let i = 0; i < count; i++) {
      const name = `f${String(i).padStart(6, "0")}.txt`;
      await writeFile(join(srcDir, name), "");
      fileNames.push(name);
    }

    const buf = await buildTarGzBuffer(srcDir, fileNames);
    const { extractTarballToDir } = await getExtractor();

    await expect(
      extractTarballToDir({ source: gunzippedReadable(buf), destDir }),
    ).rejects.toThrow("tarball exceeds entry count cap");
  }, 60_000);

  it("empty tarball rejected: zero entries throws 'tarball is empty'", async () => {
    // Create an archive with no files (empty tarball).
    // tar.c refuses to build with no files, so we build a synthetic empty tar.
    const eof = Buffer.alloc(1024, 0); // two null blocks = empty archive
    const { promisify } = await import("node:util");
    const { gzip } = await import("node:zlib");
    const gzipAsync = promisify(gzip);
    const tarGz = await gzipAsync(eof);

    const { extractTarballToDir } = await getExtractor();

    await expect(
      extractTarballToDir({ source: gunzippedReadable(tarGz), destDir }),
    ).rejects.toThrow("tarball is empty");
  });

  it("path length cap enforced: entry with path > 512 chars throws", async () => {
    const { MAX_PATH_LENGTH } = await getExtractor();
    // Build a synthetic tar with a long path using a PAX header or a raw header.
    // Simplest: write a real file with a long name and archive it.
    // Path: 513 characters of 'a'.
    const longName = "a".repeat(MAX_PATH_LENGTH + 1);
    // We can't create a file with that name on most filesystems (limit ~255).
    // We must craft a raw tar header. Use the same approach as the absolute path test,
    // but with a 513-char name. For tar, long names use the GNU LongPath extension or PAX.
    // We'll build a PAX header entry followed by a file entry with the long path.
    // Simpler: create a directory hierarchy where the relative path totals > 512 chars.
    // Use nested dirs: each dir segment is 50 chars, need 11 levels to exceed 512.
    const segment = "d".repeat(50); // 50-char segment
    // 11 levels: "d...d/d...d/...d...d/file.txt" = 50*11 + 10 (slashes) + 8 (file.txt) = 568 chars
    let currentDir = srcDir;
    const pathSegments: string[] = [];
    for (let i = 0; i < 11; i++) {
      const { mkdir: mkdirNative } = await import("node:fs/promises");
      currentDir = join(currentDir, segment);
      await mkdirNative(currentDir, { recursive: true });
      pathSegments.push(segment);
    }
    await writeFile(join(currentDir, "file.txt"), "deep");

    // Build tarball from srcDir with the deep path.
    const deepRelPath = pathSegments.join("/") + "/file.txt";
    expect(deepRelPath.length).toBeGreaterThan(MAX_PATH_LENGTH);

    const buf = await buildTarGzBuffer(srcDir, [pathSegments[0]!]);
    const { extractTarballToDir } = await getExtractor();

    await expect(
      extractTarballToDir({ source: gunzippedReadable(buf), destDir }),
    ).rejects.toThrow("tarball entry path too long");
  });
});
