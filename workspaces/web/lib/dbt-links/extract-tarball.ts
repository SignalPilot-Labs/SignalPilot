import "server-only";

import { createGunzip } from "node:zlib";
import { mkdir, writeFile, chmod } from "node:fs/promises";
import { createWriteStream } from "node:fs";
import * as path from "node:path";
import { Readable, pipeline as streamPipeline } from "node:stream";
import { promisify } from "node:util";
import { Parser } from "tar";
import type { ReadEntry } from "tar";

const pipeline = promisify(streamPipeline);

// Hardcoded caps — NOT env-configurable.
export const MAX_TOTAL_BYTES = 50 * 1024 * 1024; // 50 MiB uncompressed
export const MAX_ENTRY_COUNT = 5000;
export const MAX_PATH_LENGTH = 512;

// Entry types we accept; everything else is rejected.
const ALLOWED_TYPES = new Set(["File", "OldFile", "ContiguousFile", "Directory"]);

export interface ExtractResult {
  entryCount: number;
  totalBytes: number;
}

/**
 * Extracts a (already-gunzipped or raw) tar stream into `destDir`.
 *
 * Uses `tar.Parser` (parse-only) and writes files manually after running all
 * security validations. Does NOT use `tar.x` to avoid filter-callback
 * ambiguity about partial writes on rejection.
 *
 * `destDir` is created by this function (mode 0o700). On any throw the caller
 * is responsible for removing the partial directory.
 *
 * @param input.source  Either a Node.js Readable (pre-gunzipped tar bytes) or
 *                      a Buffer (raw tar, no gzip wrapper).
 * @param input.destDir Absolute path to the extraction target directory.
 */
export async function extractTarballToDir(input: {
  source: Readable | Buffer;
  destDir: string;
}): Promise<ExtractResult> {
  const { source, destDir } = input;

  await mkdir(destDir, { recursive: true, mode: 0o700 });

  let entryCount = 0;
  let totalBytes = 0;

  // Collect all per-entry write promises so we can await them all.
  const entryPromises: Promise<void>[] = [];
  // Track whether validation threw so we can abort cleanly.
  let validationError: Error | null = null;

  return new Promise<ExtractResult>((resolve, reject) => {
    const parser = new Parser({
      strict: true,
      onReadEntry: (entry: ReadEntry) => {
        // If a prior entry already failed validation, drain and skip.
        if (validationError !== null) {
          entry.resume();
          return;
        }

        // --- Validation: path length ---
        if (entry.path.length > MAX_PATH_LENGTH) {
          validationError = new Error("tarball entry path too long");
          entry.resume();
          return;
        }

        // --- Validation: path traversal ---
        const resolved = path.resolve(destDir, entry.path);
        if (resolved !== destDir && !resolved.startsWith(destDir + path.sep)) {
          validationError = new Error("tarball entry escapes destination");
          entry.resume();
          return;
        }

        // --- Validation: entry type ---
        if (!ALLOWED_TYPES.has(entry.type)) {
          validationError = new Error(
            "tarball contains disallowed entry type" + `: ${entry.type}`,
          );
          entry.resume();
          return;
        }

        // --- Validation: count cap ---
        entryCount += 1;
        if (entryCount > MAX_ENTRY_COUNT) {
          validationError = new Error("tarball exceeds entry count cap");
          entry.resume();
          return;
        }

        // --- Validation: size cap (per-entry contribution to running total) ---
        const entrySize = entry.size ?? 0;
        totalBytes += entrySize;
        if (totalBytes > MAX_TOTAL_BYTES) {
          validationError = new Error("tarball exceeds size cap");
          entry.resume();
          return;
        }

        const isDir =
          entry.type === "Directory" ||
          // Some tarballs encode directories as File entries with a trailing slash
          entry.path.endsWith("/");

        if (isDir) {
          // Create the directory and resume — no data to collect.
          const dirPromise = mkdir(resolved, { recursive: true, mode: 0o700 })
            .then(() => undefined as void);
          entryPromises.push(dirPromise);
          entry.resume();
          return;
        }

        // File entry: ensure parent dir exists, then stream data to disk.
        const parentDir = path.dirname(resolved);
        const filePromise = mkdir(parentDir, { recursive: true, mode: 0o700 }).then(
          () =>
            new Promise<void>((fileResolve, fileReject) => {
              const ws = createWriteStream(resolved, { mode: 0o600 });
              ws.on("error", fileReject);
              ws.on("finish", () => {
                // Enforce mode regardless of umask.
                chmod(resolved, 0o600).then(fileResolve, fileReject);
              });
              entry.pipe(ws);
            }),
        );
        entryPromises.push(filePromise);
      },
    });

    parser.on("error", (err: Error) => {
      // When the archive is entirely empty (only null blocks), the strict-mode
      // parser emits TAR_BAD_ARCHIVE before the "finish" event. Translate that
      // to a user-friendly message when no entries were seen yet.
      if (entryCount === 0) {
        reject(new Error("tarball is empty"));
      } else {
        reject(err);
      }
    });

    parser.on("finish", () => {
      // Wait for all file writes to complete, then check validation errors.
      Promise.all(entryPromises)
        .then(() => {
          if (validationError !== null) {
            reject(validationError);
            return;
          }
          if (entryCount === 0) {
            reject(new Error("tarball is empty"));
            return;
          }
          resolve({ entryCount, totalBytes });
        })
        .catch(reject);
    });

    // Pipe the source into the parser. Normalise Buffer → Readable first.
    const readable: Readable =
      Buffer.isBuffer(source) ? Readable.from(source) : (source as Readable);

    readable.pipe(parser);
    readable.on("error", reject);
  });
}
