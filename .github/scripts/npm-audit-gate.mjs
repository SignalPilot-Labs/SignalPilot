#!/usr/bin/env node
import { spawnSync } from "node:child_process";

const allowed = new Set();
for (let index = 2; index < process.argv.length; index += 1) {
  const arg = process.argv[index];
  if (arg === "--allow") {
    const value = process.argv[index + 1];
    if (!value) {
      throw new Error("--allow requires a package name");
    }
    allowed.add(value);
    index += 1;
    continue;
  }
  throw new Error(`Unknown argument: ${arg}`);
}

const audit = spawnSync(
  "npm",
  ["audit", "--audit-level=high", "--json"],
  {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  },
);

if (!audit.stdout.trim()) {
  process.stderr.write(audit.stderr);
  process.exit(audit.status ?? 1);
}

let report;
try {
  report = JSON.parse(audit.stdout);
} catch (error) {
  process.stderr.write(audit.stdout);
  process.stderr.write(audit.stderr);
  throw error;
}

const blockingSeverities = new Set(["high", "critical"]);
const vulnerabilities = Object.values(report.vulnerabilities ?? {});
const blocking = vulnerabilities.filter((vulnerability) => {
  return blockingSeverities.has(vulnerability.severity);
});

const unexpected = blocking.filter((vulnerability) => {
  return !allowed.has(vulnerability.name);
});

for (const vulnerability of blocking) {
  const prefix = allowed.has(vulnerability.name)
    ? "::warning::risk-accepted"
    : "::error::blocking";
  console.log(
    `${prefix} ${vulnerability.name} ${vulnerability.severity} ${vulnerability.range}`,
  );
}

if (unexpected.length > 0) {
  console.error(
    `npm audit found ${unexpected.length} unaccepted high/critical vulnerabilities.`,
  );
  process.exit(1);
}

const counts = report.metadata?.vulnerabilities ?? {};
console.log(
  `npm audit gate passed: ${counts.high ?? 0} high, ${counts.critical ?? 0} critical, ${allowed.size} allowlisted packages.`,
);
