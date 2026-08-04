#!/usr/bin/env node
/*
 * This script simulates the Claude CLI for end-to-end tests.
 * It accepts the production arguments.
 * It emits the production stream-json format.
 *
 * The task prompt contains the following directives:
 *   [[e2e:answer=TEXT]]: Add TEXT to the final result.
 *   [[e2e:file=PATH]]: Add the file contents to the final result.
 *   [[e2e:sql=STATEMENT]]: Run the statement with psql on SP_WAREHOUSE_DSN.
 *   [[e2e:mcp=TOOL:{...json args}]]: Call the MCP tool from --mcp-config.
 *   [[e2e:evade=TOOL:{...json args}]]: Read the key from /work/.mcp.json.
 *   Call MCP with only the key to verify the key-bound controls.
 * The script processes directives in sequence.
 * It adds MCP and SQL output to the final answer for numeric grading.
 */
"use strict";

const fs = require("fs");
const { spawnSync } = require("child_process");

function parseArgs(argv) {
  const out = { prompt: "", mcpConfig: "" };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "-p") out.prompt = argv[++i] || "";
    else if (argv[i] === "--mcp-config") out.mcpConfig = argv[++i] || "";
    else if (argv[i] === "--model" || argv[i] === "--output-format") i++;
  }
  return out;
}

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

function directives(prompt) {
  const out = [];
  const re = /\[\[e2e:(answer|sql|mcp|file|evade)=([\s\S]*?)\]\]/g;
  let m;
  while ((m = re.exec(prompt)) !== null) out.push({ kind: m[1], body: m[2] });
  return out;
}

function runSql(sql) {
  const dsn = process.env.SP_WAREHOUSE_DSN || "";
  if (!dsn) return "ERROR: no SP_WAREHOUSE_DSN in this container";
  const res = spawnSync("psql", [dsn, "-v", "ON_ERROR_STOP=1", "-Atc", sql], {
    encoding: "utf8",
    timeout: 60000,
  });
  if (res.status !== 0) return `SQL ERROR: ${(res.stderr || "").slice(0, 500)}`;
  return (res.stdout || "").trim();
}

function sseExtract(text) {
  // A streamable HTTP response can use SSE. Return the last data field.
  const lines = text.split("\n").filter((l) => l.startsWith("data:"));
  if (!lines.length) return text;
  return lines[lines.length - 1].slice(5).trim();
}

async function mcpCall(mcpConfigPath, tool, argsJson, evade) {
  const cfg = JSON.parse(fs.readFileSync(mcpConfigPath, "utf8"));
  const server = Object.values(cfg.mcpServers || {})[0];
  if (!server) return "MCP ERROR: no server in config";
  // Retain the credential and remove all other headers for this security test.
  // Model-generated code can read this file.
  // Therefore, the server must derive all access constraints from the API key.
  const supplied = server.headers || {};
  const headers = evade
    ? Object.fromEntries(Object.entries(supplied).filter(([k]) => k.toLowerCase() === "x-api-key"))
    : supplied;
  const base = { "Content-Type": "application/json", Accept: "application/json, text/event-stream", ...headers };

  async function rpc(body, extra) {
    const resp = await fetch(server.url, {
      method: "POST",
      headers: { ...base, ...(extra || {}) },
      body: JSON.stringify(body),
    });
    const sid = resp.headers.get("mcp-session-id");
    const text = await resp.text();
    return { sid, status: resp.status, text };
  }

  const init = await rpc({
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: {
      protocolVersion: "2025-03-26",
      capabilities: {},
      clientInfo: { name: "sp-eval-stub", version: "1.0" },
    },
  });
  if (init.status >= 400) return `MCP ERROR: initialize ${init.status}: ${init.text.slice(0, 300)}`;
  const session = init.sid ? { "Mcp-Session-Id": init.sid } : {};

  await rpc({ jsonrpc: "2.0", method: "notifications/initialized" }, session);

  let args;
  try {
    args = JSON.parse(argsJson);
  } catch (e) {
    return `MCP ERROR: bad args json: ${e}`;
  }
  const call = await rpc(
    { jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: tool, arguments: args } },
    session
  );
  if (call.status >= 400) return `MCP ERROR: tools/call ${call.status}: ${call.text.slice(0, 300)}`;
  try {
    const payload = JSON.parse(sseExtract(call.text));
    const content = ((payload.result || {}).content || [])
      .map((c) => (c && c.text) || "")
      .join("\n");
    return content || JSON.stringify(payload.result || payload).slice(0, 1000);
  } catch (e) {
    return call.text.slice(0, 1000);
  }
}

(async () => {
  const { prompt, mcpConfig } = parseArgs(process.argv.slice(2));
  emit({ type: "system", subtype: "init", model: "stub", tools: [] });

  const parts = [];
  for (const d of directives(prompt)) {
    if (d.kind === "answer") {
      parts.push(d.body);
    } else if (d.kind === "file") {
      try {
        parts.push(fs.readFileSync(d.body, "utf8").trim());
      } catch (e) {
        parts.push(`FILE ERROR: ${e.message || e}`);
      }
    } else if (d.kind === "sql") {
      emit({ type: "assistant", message: { content: [{ type: "text", text: `running sql: ${d.body.slice(0, 120)}` }] } });
      parts.push(runSql(d.body));
    } else if (d.kind === "mcp" || d.kind === "evade") {
      const idx = d.body.indexOf(":");
      const tool = d.body.slice(0, idx);
      const argsJson = d.body.slice(idx + 1);
      emit({ type: "assistant", message: { content: [{ type: "tool_use", name: `mcp__signalpilot__${tool}`, input: JSON.parse(argsJson) }] } });
      parts.push(await mcpCall(mcpConfig, tool, argsJson, d.kind === "evade"));
    }
  }
  const result = parts.length ? parts.join("\n") : "stub: no e2e directives in prompt";
  emit({ type: "result", subtype: "success", result });
})().catch((e) => {
  emit({ type: "result", subtype: "error", result: `stub crashed: ${e && e.stack ? e.stack : e}` });
  process.exit(1);
});
