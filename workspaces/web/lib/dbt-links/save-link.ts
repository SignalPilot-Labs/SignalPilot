"use server";

import { createGunzip } from "node:zlib";
import { writeFile, rename, chmod, mkdir, rm } from "node:fs/promises";
import * as path from "node:path";
import { Readable } from "node:stream";
import { getServerEnv } from "@/lib/env";
import { isGzipMagic } from "@/lib/dbt-links/sniff-gzip";
import { extractTarballToDir } from "@/lib/dbt-links/extract-tarball";
import type { DbtLinkV1 } from "@/lib/dbt-links/types";

// Allowed compressed content-types. application/octet-stream is included
// because some browsers report it as a fallback for .tar.gz uploads;
// the magic-byte sniff below is the real gate, not this allowlist.
const ALLOWED_CONTENT_TYPES = new Set([
  "application/gzip",
  "application/x-gzip",
  "application/octet-stream",
]);

const COMPRESSED_SIZE_CAP = 50 * 1024 * 1024; // 50 MiB

export async function saveDbtLinkNativeUpload(
  formData: FormData,
): Promise<{ ok: true; id: string } | { ok: false; error: string }> {
  // Step 1: mode gate — throws on cloud, no catch swallow.
  const env = getServerEnv();
  if (env.mode !== "local") {
    throw new Error("saveDbtLinkNativeUpload is only available in local mode");
  }

  // Step 2: validate name.
  const rawName = formData.get("name");
  if (typeof rawName !== "string") {
    return { ok: false, error: "Name is required." };
  }
  const name = rawName.trim();
  if (name.length === 0 || name.length > 120) {
    return { ok: false, error: "Name must be between 1 and 120 characters." };
  }

  // Step 3: validate file field. Accept any object with File-like properties
  // (size, name, type, stream) since the global File class differs between
  // Next.js server runtime and test environments.
  const fileRaw = formData.get("file");
  if (
    typeof fileRaw !== "object" ||
    fileRaw === null ||
    !("size" in fileRaw) ||
    !("name" in fileRaw) ||
    !("type" in fileRaw) ||
    typeof (fileRaw as { stream?: unknown }).stream !== "function"
  ) {
    return { ok: false, error: "File is required." };
  }
  const file = fileRaw as File;

  // Step 4: reject empty file.
  if (file.size === 0) {
    return { ok: false, error: "Uploaded file is empty." };
  }

  // Step 5: cap compressed file size independently of extractor's uncompressed cap.
  if (file.size > COMPRESSED_SIZE_CAP) {
    return { ok: false, error: "Uploaded file exceeds 50 MiB." };
  }

  // Step 6: content-type allowlist.
  if (!ALLOWED_CONTENT_TYPES.has(file.type)) {
    return { ok: false, error: "Unsupported file type. Upload a .tar.gz." };
  }

  // Step 7: magic-byte sniff — read first 2 bytes WITHOUT consuming file.stream().
  // Each call to file.stream() creates a new ReadableStream from the same Blob data,
  // so reading 2 bytes here does not affect the stream used for extraction.
  const headBytes = await (async (): Promise<Uint8Array> => {
    const stream = file.stream() as unknown as ReadableStream<Uint8Array>;
    const reader = stream.getReader();
    try {
      const { value } = await reader.read();
      return value ? value.slice(0, 2) : new Uint8Array(0);
    } finally {
      await reader.cancel();
    }
  })();
  const head = headBytes;
  if (!isGzipMagic(head)) {
    return { ok: false, error: "File is not a valid gzip archive." };
  }

  // Steps 8–9: generate server-side IDs.
  const id = (await import("node:crypto")).randomUUID();
  const createdAt = new Date().toISOString();
  const relativePath = id;

  // Step 10: ensure parent dir exists.
  const localDbtLinksDir = env.localDbtLinksDir;
  await mkdir(localDbtLinksDir, { recursive: true });

  // Step 11: destination dir for extracted files.
  const destDir = path.join(localDbtLinksDir, id);

  // Step 12: extract — on failure, clean up partial dir and return error.
  try {
    const fileStream = Readable.from(
      (file.stream() as unknown) as AsyncIterable<Uint8Array>,
    );
    const gunzip = createGunzip();
    const tarStream = fileStream.pipe(gunzip);
    await extractTarballToDir({ source: tarStream, destDir });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`saveDbtLinkNativeUpload: extraction failed for id=${id}:`, err);
    try {
      await rm(destDir, { recursive: true, force: true });
    } catch (cleanupErr) {
      console.error(
        `saveDbtLinkNativeUpload: cleanup of destDir failed for id=${id}:`,
        cleanupErr,
      );
    }
    return { ok: false, error: `Could not extract archive: ${msg}` };
  }

  // Step 13: build manifest.
  const manifest: DbtLinkV1 = {
    schemaVersion: 1,
    id,
    name,
    kind: "native_upload",
    createdAt,
    relativePath,
  };

  // Step 14: atomic write — tmp → writeFile → rename → chmod 0o600.
  const finalPath = path.join(localDbtLinksDir, `${id}.json`);
  // Use explicit ".json.tmp" suffix to match atomic-write convention.
  const tmpPath = path.join(localDbtLinksDir, `${id}.json.tmp`);

  try {
    const json = JSON.stringify(manifest, null, 2);
    await writeFile(tmpPath, json, { encoding: "utf-8" });
    await rename(tmpPath, finalPath);
    await chmod(finalPath, 0o600);
  } catch (manifestErr) {
    // Step 15: on manifest write failure, remove extracted dir and rethrow.
    console.error(
      `saveDbtLinkNativeUpload: manifest write failed for id=${id}:`,
      manifestErr,
    );
    try {
      await rm(destDir, { recursive: true, force: true });
    } catch (cleanupErr) {
      console.error(
        `saveDbtLinkNativeUpload: cleanup of destDir after manifest failure for id=${id}:`,
        cleanupErr,
      );
    }
    throw manifestErr;
  }

  // Step 16: success.
  return { ok: true, id };
}
