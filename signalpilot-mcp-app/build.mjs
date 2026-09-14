import { mkdir, writeFile } from "node:fs/promises";
import { gzipSync } from "node:zlib";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const output = resolve(here, "../signalpilot/gateway/gateway/mcp/apps/pulse.html");
// zod + the MCP client SDK + React are ~200 KB gzipped; the embedded fonts ~60 KB.
const BUDGET_BYTES = 400_000;

const result = await build({
  absWorkingDir: here,
  entryPoints: [resolve(here, "src/main.tsx")],
  bundle: true,
  write: false,
  minify: true,
  format: "iife",
  platform: "browser",
  target: "es2022",
  outfile: "pulse.js",
  metafile: true,
  define: { "process.env.NODE_ENV": '"production"' },
  loader: { ".woff2": "dataurl" },
  legalComments: "none",
});

const js = result.outputFiles.find((file) => file.path.endsWith(".js")).text;
const css = result.outputFiles.find((file) => file.path.endsWith(".css"))?.text ?? "";
const pack = (text) => gzipSync(text, { level: 9 }).toString("base64");

// Script and stylesheet ship gzipped inside the HTML and inflate themselves
// with the browser's DecompressionStream, which keeps the resource inside the
// host size budget while staying a single self-contained document.
const boot = `(async()=>{try{const inflate=async(b64)=>{const bytes=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));return new Response(stream).text()};const style=document.createElement("style");style.textContent=await inflate("${pack(css)}");document.head.append(style);const script=document.createElement("script");script.textContent=await inflate("${pack(js)}");document.body.append(script);script.remove()}catch{document.getElementById("root").textContent="SignalPilot Pulse could not start. Reload this app or open the chat in SignalPilot."}})();`;

const html = [
  "<!doctype html><html><head><meta charset=\"utf-8\">",
  "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
  "<title>SignalPilot Pulse</title>",
  "<style>html,body{margin:0;background:transparent}.boot-text{font:12.5px system-ui,sans-serif;color:#8a8a8a;padding:16px}</style></head>",
  "<body><div id=\"root\"><main class=\"pulse\" data-phase=\"booting\"><p class=\"boot-text\" role=\"status\">Connecting to SignalPilot…</p></main></div>",
  `<script>${boot}</script></body></html>`,
].join("");

const inputs = Object.keys(result.metafile.inputs);
if (inputs.some((input) => input.includes("node_modules/next/"))) throw new Error("Next runtime leaked into the MCP app");
if (Buffer.byteLength(html) > BUDGET_BYTES) throw new Error(`Pulse bundle is ${Buffer.byteLength(html)} bytes, over the ${BUDGET_BYTES} budget`);

await mkdir(dirname(output), { recursive: true });
await writeFile(output, html);
console.log(`Pulse app: ${Buffer.byteLength(html)} bytes → ${output}`);
