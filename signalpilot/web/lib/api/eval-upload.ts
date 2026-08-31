// Evaluation upload helpers for the /evals/upload page.

import { request } from "./client";

// The following functions support uploads from the /evals/upload page.
// The gateway creates presigned PUT URLs for each S3 part.
// The browser uploads parts directly to S3 in parallel.
// The browser retries each part and then requests upload completion.
// File data does not pass through the gateway.
// The part uploads use XHR because fetch does not report upload progress.
export type EvalUploadResult = { reference_id: string; expires_at: string };

type EvalUploadInitiate = {
  key: string;
  upload_id: string;
  reference_id: string;
  part_size: number;
  part_urls: string[];
};

const PART_CONCURRENCY = 4;
const PART_RETRIES = 3;

function putPart(
  url: string,
  blob: Blob,
  onBytes: (loaded: number) => void,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.upload.onprogress = (e) => onBytes(e.loaded);
    xhr.onload = () => {
      const etag = xhr.getResponseHeader("ETag");
      if (xhr.status >= 200 && xhr.status < 300 && etag) {
        onBytes(blob.size);
        resolve(etag);
      } else {
        reject(
          new Error(
            `Part upload failed (${xhr.status}${etag ? "" : ", no ETag"})`,
          ),
        );
      }
    };
    xhr.onerror = () => reject(new Error("Network error during part upload"));
    xhr.send(blob);
  });
}

async function putPartWithRetry(
  url: string,
  blob: Blob,
  onBytes: (loaded: number) => void,
): Promise<string> {
  let lastErr: unknown;
  for (let attempt = 0; attempt < PART_RETRIES; attempt++) {
    try {
      return await putPart(url, blob, onBytes);
    } catch (err) {
      lastErr = err;
      onBytes(0);
      await new Promise((r) => setTimeout(r, 1000 * 2 ** attempt));
    }
  }
  throw lastErr;
}

export async function uploadEval(
  file: File,
  notes: string,
  onProgress?: (pct: number) => void,
): Promise<EvalUploadResult> {
  let init: EvalUploadInitiate;
  try {
    init = await request<EvalUploadInitiate>("/api/evals/upload/initiate", {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        size_bytes: file.size,
        notes,
      }),
    });
  } catch (err) {
    // request() includes the status and body in the error.
    // Return the status and detail for the page error message.
    const m = /^(\d{3}): (.*)$/s.exec((err as Error).message ?? "");
    if (m) {
      let detail = "";
      try {
        detail = (JSON.parse(m[2]) as { detail?: string })?.detail ?? "";
      } catch {}
      throw Object.assign(new Error(detail || m[2]), { status: Number(m[1]) });
    }
    throw err;
  }

  const partCount = init.part_urls.length;
  const loaded = new Array<number>(partCount).fill(0);
  const report = () => {
    if (onProgress) {
      const total = loaded.reduce((a, b) => a + b, 0);
      onProgress(Math.min(99, Math.round((total / file.size) * 100)));
    }
  };

  const etags = new Array<string>(partCount);
  let next = 0;
  try {
    const worker = async () => {
      while (next < partCount) {
        const i = next++;
        const blob = file.slice(
          i * init.part_size,
          Math.min((i + 1) * init.part_size, file.size),
        );
        etags[i] = await putPartWithRetry(init.part_urls[i], blob, (n) => {
          loaded[i] = n;
          report();
        });
      }
    };
    await Promise.all(
      Array.from({ length: Math.min(PART_CONCURRENCY, partCount) }, worker),
    );
  } catch (err) {
    // Abort the upload when possible.
    // The bucket lifecycle rule removes incomplete upload data.
    request("/api/evals/upload/abort", {
      method: "POST",
      body: JSON.stringify({ key: init.key, upload_id: init.upload_id }),
    }).catch(() => {});
    throw err;
  }

  const result = await request<EvalUploadResult>("/api/evals/upload/complete", {
    method: "POST",
    body: JSON.stringify({
      key: init.key,
      upload_id: init.upload_id,
      parts: etags.map((etag, i) => ({ part_number: i + 1, etag })),
      notes,
    }),
  });
  if (onProgress) onProgress(100);
  return result;
}
