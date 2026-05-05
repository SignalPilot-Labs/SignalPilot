import { NextRequest, NextResponse } from "next/server";
import { type IncomingMessage, request as httpRequest } from "node:http";
import { getServerEnv } from "@/lib/env";
import { loadAgentRun } from "@/lib/agent-runs/load-runs";
import { writeFile } from "node:fs/promises";
import { join } from "node:path";

export const dynamic = "force-dynamic";

function connectUpstream(
  sandboxUrl: string,
  secret: string,
): Promise<IncomingMessage> {
  return new Promise((resolve, reject) => {
    const url = new URL(sandboxUrl);
    const req = httpRequest(
      {
        hostname: url.hostname,
        port: url.port,
        path: url.pathname,
        method: "GET",
        headers: {
          "X-Internal-Secret": secret,
          Accept: "text/event-stream",
        },
      },
      resolve,
    );
    req.on("error", reject);
    req.end();
  });
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const env = getServerEnv();
  if (env.mode !== "local") {
    return NextResponse.json({ error: "local mode only" }, { status: 400 });
  }

  const { id } = await params;
  const run = await loadAgentRun(id);
  if (!run || !run.sessionId) {
    return NextResponse.json(
      { error: "run not found or no session" },
      { status: 404 },
    );
  }

  const sandboxUrl = `${env.sandboxUrl}/session/${run.sessionId}/events`;

  let upstream: IncomingMessage;
  try {
    upstream = await connectUpstream(sandboxUrl, env.sandboxSecret);
  } catch {
    return NextResponse.json({ error: "sandbox unreachable" }, { status: 502 });
  }

  if (upstream.statusCode !== 200) {
    upstream.destroy();
    return NextResponse.json(
      { error: `sandbox returned ${upstream.statusCode}` },
      { status: 502 },
    );
  }

  const decoder = new TextDecoder();
  let statusWritten = false;

  const stream = new ReadableStream({
    start(controller) {
      upstream.on("data", (chunk: Buffer) => {
        controller.enqueue(new Uint8Array(chunk));

        if (statusWritten) return;
        const text = decoder.decode(chunk, { stream: true });

        if (text.includes("event: result")) {
          statusWritten = true;
          const lines = text.split("\n");
          const dataLine = lines.find(
            (l) => l.startsWith("data:") && l.includes("total_cost_usd"),
          );
          if (dataLine) {
            try {
              const data = JSON.parse(dataLine.slice(5).trim());
              const summary = `Cost: $${data.total_cost_usd?.toFixed(4) ?? "?"} | Turns: ${data.num_turns ?? "?"}`;
              const updated = { ...run, status: "succeeded", finishedAt: new Date().toISOString(), summary };
              writeFile(join(env.localAgentRunsDir, `${id}.json`), JSON.stringify(updated, null, 2)).catch(() => {});
            } catch { /* best-effort */ }
          }
        }

        if (text.includes("event: session_end") || text.includes("event: session_error")) {
          if (!statusWritten) {
            statusWritten = true;
            const isError = text.includes("event: session_error");
            const updated = {
              ...run,
              status: isError ? "failed" : "succeeded",
              finishedAt: new Date().toISOString(),
              ...(isError ? { errorMessage: "Session ended with error" } : {}),
            };
            writeFile(join(env.localAgentRunsDir, `${id}.json`), JSON.stringify(updated, null, 2)).catch(() => {});
          }
        }
      });

      upstream.on("end", () => {
        controller.close();
      });

      upstream.on("error", () => {
        controller.close();
      });
    },
    cancel() {
      upstream.destroy();
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
