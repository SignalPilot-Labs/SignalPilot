const FORWARDED_PARAMS = ["file", "project", "branch"] as const;

/**
 * Thrown when the `/api/mount-config` fetch fails (non-2xx or network error).
 * Callers should surface this as a boot error, not a silent default.
 */
export class MountConfigError extends Error {
  readonly status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.status = status;
    this.name = "MountConfigError";
  }
}

interface FetchMountConfigOptions {
  /**
   * Explicit search params to forward. When provided, these are used instead
   * of `window.location.search`. Decouples warm-reboot callers from global
   * URL mutation ordering.
   */
  search?: URLSearchParams;
}

/**
 * Fetch the mount config from the backend.
 *
 * Forwards only `file`, `project`, and `branch` from the current URL's query
 * params (or from `opts.search` if provided). `access_token` is intentionally
 * NOT forwarded — the backend strips it from the redirect before serving the
 * HTML and it must not appear in API calls.
 *
 * Returns the raw JSON (validation happens inside `mount()` / `initStore` via
 * `mountOptionsSchema`).
 *
 * Fails fast: throws `MountConfigError` on any non-2xx or network failure.
 * No retry, no fallback.
 */
export async function fetchMountConfig(
  opts?: FetchMountConfigOptions,
): Promise<unknown> {
  const params = new URLSearchParams();
  const source = opts?.search ?? new URLSearchParams(window.location.search);
  for (const key of FORWARDED_PARAMS) {
    const val = source.get(key);
    if (val !== null) {
      params.set(key, val);
    }
  }

  const query = params.toString();
  const url = `/api/mount-config${query ? `?${query}` : ""}`;

  let response: Response;
  try {
    response = await fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
  } catch (err) {
    throw new MountConfigError(
      `Network error fetching mount config: ${err instanceof Error ? err.message : String(err)}`,
    );
  }

  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? "";
    } catch {
      // ignore parse failure
    }
    throw new MountConfigError(
      `Mount config request failed: ${response.status}${detail ? ` — ${detail}` : ""}`,
      response.status,
    );
  }

  return response.json();
}
