import { readdirSync, readFileSync } from "node:fs";
import { extname, join, relative } from "node:path";

const root = process.cwd();
const targets = [
  join(root, "app", "connections"),
  join(root, "components", "connections"),
  join(root, "lib", "connections"),
];
const limit = 800;
const sourceExtensions = new Set([".ts", ".tsx"]);

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return sourceExtensions.has(extname(path)) ? [path] : [];
  });
}

const oversized = targets
  .flatMap(sourceFiles)
  .map((path) => ({
    path,
    lines: readFileSync(path, "utf8").split(/\r?\n/).length,
  }))
  .filter((file) => file.lines > limit);

if (oversized.length > 0) {
  for (const file of oversized) {
    console.error(`${relative(root, file.path)} has ${file.lines} lines. The limit is ${limit}.`);
  }
  process.exit(1);
}

console.log(`Connection source files are within the ${limit}-line limit.`);
