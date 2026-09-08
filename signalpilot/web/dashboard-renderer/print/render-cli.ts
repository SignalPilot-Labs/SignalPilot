/**
 * Node entry: `node render-cli.js --out <png> [--width 1280] [--theme light|dark]`.
 * Reads `{ spec, datasets, chart_ids }` JSON from stdin, writes a PNG and
 * prints one JSON status line. Exit 0 ok, 2 invalid input, 3 timeout.
 *
 * Bundled by ../build-cli.mjs (everything except @resvg/resvg-js).
 * Print-path module: relative imports only, no React, no DOM, no network.
 */
import { existsSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

import { Resvg } from "@resvg/resvg-js";

import type { DatasetRows } from "../datasets";
import { validateDashboardSpec } from "../schema";
import { composeDashboardSvg } from "./compose";

export const RENDER_TIMEOUT_MS = 10_000;
export const DEFAULT_WIDTH = 1280;

export type CliArgs = { out?: string; width: number; theme: "light" | "dark" };

export function parseArgs(argv: string[]): CliArgs {
  const args: CliArgs = { width: DEFAULT_WIDTH, theme: "light" };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const [flag, inline] = arg.startsWith("--") && arg.includes("=") ? arg.split(/=(.*)/s) : [arg];
    const next = () => (inline !== undefined ? inline : argv[++index]);
    if (flag === "--out") args.out = next();
    else if (flag === "--width") {
      const width = Number(next());
      if (Number.isFinite(width) && width > 0) args.width = Math.round(width);
    } else if (flag === "--theme") {
      const theme = next();
      if (theme === "dark" || theme === "light") args.theme = theme;
    }
  }
  return args;
}

/** Every *.ttf under `<dir>/fonts/` (falls back to `<dir>/../fonts/`). */
export function fontFiles(baseDir: string): string[] {
  for (const candidate of [join(baseDir, "fonts"), join(baseDir, "..", "fonts")]) {
    if (!existsSync(candidate)) continue;
    const files = readdirSync(candidate)
      .filter((name) => /\.ttf$/i.test(name))
      .map((name) => join(candidate, name));
    if (files.length) return files;
  }
  return [];
}

export type StdinPayload = {
  spec: unknown;
  datasets?: Record<string, DatasetRows>;
  chart_ids?: string[] | null;
};

export function svgToPng(svg: string, width: number, fonts: string[]): Buffer {
  const resvg = new Resvg(svg, {
    fitTo: { mode: "width", value: width },
    font: {
      fontFiles: fonts,
      defaultFontFamily: "DM Sans",
      loadSystemFonts: true,
    },
  });
  return Buffer.from(resvg.render().asPng());
}

export type RenderOutcome =
  | { ok: true; rendered: string[]; failed: { id: string; code: string; message: string }[]; width: number; height: number; png: Buffer }
  | { ok: false; errors: string[] };

/** Validate, compose and rasterize. Pure with respect to process/stdio. */
export function renderFromPayload(
  payload: StdinPayload,
  args: CliArgs,
  fonts: string[],
): RenderOutcome {
  const validation = validateDashboardSpec(payload.spec);
  if (!validation.ok) return { ok: false, errors: validation.errors };
  const datasets = payload.datasets ?? {};
  const composed = composeDashboardSvg({
    spec: validation.spec,
    datasets,
    chartIds: Array.isArray(payload.chart_ids) ? payload.chart_ids : null,
    width: args.width,
    theme: args.theme,
  });
  const png = svgToPng(composed.svg, composed.width, fonts);
  return {
    ok: true,
    rendered: composed.rendered,
    failed: composed.failed,
    width: composed.width,
    height: composed.height,
    png,
  };
}

function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    process.stdin.on("data", (chunk: Buffer) => chunks.push(chunk));
    process.stdin.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    process.stdin.on("error", reject);
  });
}

function emit(status: object): void {
  process.stdout.write(`${JSON.stringify(status)}\n`);
}

async function main(): Promise<number> {
  const args = parseArgs(process.argv.slice(2));
  if (!args.out) {
    emit({ ok: false, errors: ["--out <png path> is required"] });
    return 2;
  }
  let payload: StdinPayload;
  try {
    const text = await readStdin();
    const parsed: unknown = JSON.parse(text);
    if (parsed === null || typeof parsed !== "object" || !("spec" in parsed)) {
      emit({ ok: false, errors: ["stdin JSON must be an object with a \"spec\" key"] });
      return 2;
    }
    payload = parsed as StdinPayload;
  } catch (error) {
    emit({ ok: false, errors: [`stdin is not valid JSON: ${error instanceof Error ? error.message : String(error)}`] });
    return 2;
  }
  const fonts = fontFiles(dirname(__filename));
  const outcome = renderFromPayload(payload, args, fonts);
  if (!outcome.ok) {
    emit({ ok: false, errors: outcome.errors });
    return 2;
  }
  writeFileSync(args.out, outcome.png);
  emit({
    ok: true,
    rendered: outcome.rendered,
    failed: outcome.failed,
    width: outcome.width,
    height: outcome.height,
  });
  return 0;
}

const isEntry =
  typeof require !== "undefined" && typeof module !== "undefined" && require.main === module;

if (isEntry) {
  const timer = setTimeout(() => {
    emit({ ok: false, errors: ["timeout"] });
    process.exit(3);
  }, RENDER_TIMEOUT_MS);
  main()
    .then((code) => {
      clearTimeout(timer);
      process.exitCode = code;
    })
    .catch((error) => {
      clearTimeout(timer);
      emit({ ok: false, errors: [error instanceof Error ? error.message : String(error)] });
      process.exitCode = 2;
    });
}
