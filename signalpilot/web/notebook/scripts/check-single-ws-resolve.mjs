#!/usr/bin/env node
/**
 * Static gate for F-16: assert that useSpKernelConnection.tsx makes exactly
 * ONE call to runtimeManager.getWsURL per connection attempt by using the
 * resolveWsOnce helper.
 *
 * Violations caught:
 *   - More than one occurrence of `runtimeManager.getWsURL` in the file
 *     (reverted double-call pattern).
 *   - Missing `resolveWsOnce` reference in the `url:` factory arrow.
 *   - Missing `resolveWsOnce` reference in the `protocols:` factory arrow.
 *
 * Usage:
 *   node signalpilot/web/notebook/scripts/check-single-ws-resolve.mjs
 *
 * Exit 0 → all assertions pass.
 * Exit 1 → at least one assertion failed (violation message printed to stderr).
 */

import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const HOOK_PATH = resolve(
  __dirname,
  "../core/websocket/useSpKernelConnection.tsx",
);

const source = readFileSync(HOOK_PATH, "utf8");

let failed = false;

function fail(msg) {
  process.stderr.write(`FAIL: ${msg}\n`);
  failed = true;
}

// --- Assertion 1: exactly ONE occurrence of runtimeManager.getWsURL ---
const getWsURLMatches = (source.match(/runtimeManager\.getWsURL/g) ?? []).length;
if (getWsURLMatches !== 1) {
  fail(
    `Expected exactly 1 occurrence of 'runtimeManager.getWsURL' but found ${getWsURLMatches}. ` +
      "The double-call pattern creates a TOCTOU window on Clerk JWT rotation.",
  );
} else {
  process.stdout.write("PASS: exactly 1 occurrence of runtimeManager.getWsURL\n");
}

// --- Assertion 2: url factory uses resolveWsOnce ---
// Match the `url:` property arrow — allow for optional `async` and whitespace.
const urlFactoryMatch = source.match(/url:\s*async\s*\(\s*\)\s*=>\s*[^\n]+/);
if (!urlFactoryMatch) {
  fail("Could not locate 'url: async () =>' factory in the hook.");
} else if (!urlFactoryMatch[0].includes("resolveWsOnce")) {
  fail(
    `'url:' factory does not call resolveWsOnce. Found: ${urlFactoryMatch[0].trim()}`,
  );
} else {
  process.stdout.write("PASS: url factory uses resolveWsOnce\n");
}

// --- Assertion 3: protocols factory uses resolveWsOnce ---
const protocolsFactoryMatch = source.match(/protocols:\s*async\s*\(\s*\)\s*=>\s*[^\n]+/);
if (!protocolsFactoryMatch) {
  fail("Could not locate 'protocols: async () =>' factory in the hook.");
} else if (!protocolsFactoryMatch[0].includes("resolveWsOnce")) {
  fail(
    `'protocols:' factory does not call resolveWsOnce. Found: ${protocolsFactoryMatch[0].trim()}`,
  );
} else {
  process.stdout.write("PASS: protocols factory uses resolveWsOnce\n");
}

if (failed) {
  process.exit(1);
}

process.stdout.write("\nAll assertions passed — single WS resolve invariant holds.\n");
