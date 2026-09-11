// Bundles print/render-cli.ts into dist/render-cli.js and copies fonts/ next
// to it. Runs from the web app (`pnpm build:dashboard-cli`) or standalone
// inside this directory (`npm run build`), using whichever node_modules
// resolves esbuild.
import { cpSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const dist = join(here, "dist");
mkdirSync(dist, { recursive: true });

await build({
  entryPoints: [join(here, "print", "render-cli.ts")],
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node20",
  external: ["@resvg/resvg-js"],
  outfile: join(dist, "render-cli.js"),
  logLevel: "info",
  legalComments: "none",
});

const fonts = join(here, "fonts");
if (existsSync(fonts)) {
  const target = join(dist, "fonts");
  mkdirSync(target, { recursive: true });
  for (const name of readdirSync(fonts)) {
    if (/\.(ttf|txt)$/i.test(name)) cpSync(join(fonts, name), join(target, name));
  }
}
console.log(`built ${join(dist, "render-cli.js")}`);
