"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  Play,
  Loader2,
  Trash2,
  Clock,
  Cpu,
  Database,
  DollarSign,
  Shield,
  Download,
  Maximize2,
  Minimize2,
  Copy,
  Check,
  Image as ImageIcon,
  FileText,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { getSandbox, executeSandbox, deleteSandbox } from "@/lib/api";
import type { SandboxInfo } from "@/lib/types";
import { StatusDot, MiniBar } from "@/components/ui/data-viz";
import { useToast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { CodeBlock } from "@/components/ui/code-block";

interface HistoryEntry {
  type: "input" | "output" | "error" | "system" | "image" | "html";
  text: string;
  timestamp: number;
  execution_ms?: number;
  imageData?: string;
  htmlContent?: string;
}

// Pure allowlist sanitizer for pandas DataFrame HTML tables.
// Keeps only known-safe table elements and a minimal set of safe attributes.
// Any element or attribute not in the allowlist is removed — this is NOT a
// denylist; we do not enumerate bad things, we enumerate the only good things.
// style is intentionally excluded: it is a CSS injection vector even without JS.
const ALLOWED_TABLE_ELEMENTS = new Set([
  "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col",
]);
const ALLOWED_TABLE_ATTRS = new Set(["colspan", "rowspan", "class"]);

function sanitizeTableHtml(html: string): string {
  const doc = new DOMParser().parseFromString(html, "text/html");

  // Walk every element in the document. Collect in reverse document order so
  // removing a node does not invalidate the iteration of its ancestors.
  const allElements = Array.from(doc.body.querySelectorAll("*")).reverse();
  for (const el of allElements) {
    if (!ALLOWED_TABLE_ELEMENTS.has(el.tagName.toLowerCase())) {
      // Replace disallowed element with its text content so we don't silently
      // swallow visible text that happened to be wrapped in a bad tag.
      el.replaceWith(document.createTextNode(el.textContent ?? ""));
      continue;
    }
    // Strip disallowed attributes from allowed elements.
    const attrNames = Array.from(el.attributes).map((a) => a.name);
    for (const attr of attrNames) {
      if (!ALLOWED_TABLE_ATTRS.has(attr.toLowerCase())) {
        el.removeAttribute(attr);
      }
    }
  }

  // Serialize only the body content back to a string.
  return doc.body.innerHTML;
}

function extractRichOutput(output: string): {
  text: string;
  images: string[];
  html: string | null;
} {
  const images: string[] = [];
  let html: string | null = null;
  let text = output;

  const imgRegex = /data:image\/(png|jpeg|svg\+xml);base64,[A-Za-z0-9+/=]+/g;
  let match;
  while ((match = imgRegex.exec(output)) !== null) {
    images.push(match[0]);
    text = text.replace(match[0], `[Image ${images.length}]`);
  }

  const htmlTableMatch = output.match(/<table[\s\S]*?<\/table>/i);
  if (htmlTableMatch) {
    html = sanitizeTableHtml(htmlTableMatch[0]);
    text = text.replace(htmlTableMatch[0], "[HTML Table]");
  }

  return { text: text.trim(), images, html };
}

const EXAMPLE_SNIPPETS = [
  {
    label: "data analysis",
    code: `import pandas as pd
import numpy as np

# Create sample data
df = pd.DataFrame({
    'date': pd.date_range('2024-01-01', periods=30),
    'revenue': np.random.uniform(1000, 5000, 30),
    'users': np.random.randint(100, 1000, 30)
})

print(df.describe())`,
  },
  {
    label: "chart",
    code: `import matplotlib.pyplot as plt
import numpy as np

x = np.linspace(0, 10, 100)
plt.figure(figsize=(8, 4))
plt.plot(x, np.sin(x), label='sin(x)')
plt.plot(x, np.cos(x), label='cos(x)')
plt.legend()
plt.title('Trigonometric Functions')
plt.grid(True, alpha=0.3)
plt.savefig('/tmp/chart.png', dpi=100, bbox_inches='tight')
print("Chart saved to /tmp/chart.png")`,
  },
  {
    label: "sql query",
    code: `# Query through the governed gateway
import requests
import os

resp = requests.post(f"{os.environ.get('SP_GATEWAY_URL', 'http://localhost:3300')}/api/query", json={
    "connection_name": "default",
    "sql": "SELECT * FROM users LIMIT 5",
    "row_limit": 100
})
print(resp.json())`,
  },
];

export default function SandboxDetailPage() {
  const params = useParams();
  const router = useRouter();
  const sandboxId = params.id as string;

  const [sandbox, setSandbox] = useState<SandboxInfo | null>(null);
  const [code, setCode] = useState("");
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showSnippets, setShowSnippets] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { toast } = useToast();
  const [showKillConfirm, setShowKillConfirm] = useState(false);

  useEffect(() => {
    getSandbox(sandboxId)
      .then((sb) => {
        setSandbox(sb);
        setHistory([
          {
            type: "system",
            text: `sandbox ${sb.label || sb.id.slice(0, 8)} ready. ${
              sb.connection_name ? `connected: ${sb.connection_name}` : "no database connection."
            }\nbudget: $${sb.budget_usd.toFixed(2)} | row_limit: ${sb.row_limit.toLocaleString()} | status: ${sb.status}`,
            timestamp: Date.now(),
          },
        ]);
      })
      .catch((e) => setError(String(e)));
  }, [sandboxId]);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [history]);

  useEffect(() => {
    const i = setInterval(() => {
      getSandbox(sandboxId).then(setSandbox).catch(() => {});
    }, 10000);
    return () => clearInterval(i);
  }, [sandboxId]);

  const handleExecute = useCallback(async () => {
    if (!code.trim() || running) return;

    const input = code.trim();
    setCode("");
    setRunning(true);

    setHistory((h) => [
      ...h,
      { type: "input", text: input, timestamp: Date.now() },
    ]);

    try {
      const result = await executeSandbox(sandboxId, input, 30);
      if (result.success) {
        const rich = extractRichOutput(result.output || "(no output)");

        if (rich.text) {
          setHistory((h) => [
            ...h,
            {
              type: "output",
              text: rich.text,
              timestamp: Date.now(),
              execution_ms: result.execution_ms ?? undefined,
            },
          ]);
        }

        for (const img of rich.images) {
          setHistory((h) => [
            ...h,
            { type: "image", text: "", imageData: img, timestamp: Date.now() },
          ]);
        }

        if (rich.html) {
          const htmlStr = rich.html;
          setHistory((h) => [
            ...h,
            { type: "html", text: "", htmlContent: htmlStr, timestamp: Date.now() },
          ]);
        }
      } else {
        setHistory((h) => [
          ...h,
          {
            type: "error",
            text: result.error || "Execution failed",
            timestamp: Date.now(),
            execution_ms: result.execution_ms ?? undefined,
          },
        ]);
      }
      getSandbox(sandboxId).then(setSandbox).catch(() => {});
    } catch (e) {
      setHistory((h) => [
        ...h,
        { type: "error", text: String(e), timestamp: Date.now() },
      ]);
    } finally {
      setRunning(false);
      textareaRef.current?.focus();
    }
  }, [code, running, sandboxId]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleExecute();
    }
    if (e.key === "Tab") {
      e.preventDefault();
      const target = e.target as HTMLTextAreaElement;
      const start = target.selectionStart;
      const end = target.selectionEnd;
      setCode(code.substring(0, start) + "    " + code.substring(end));
      setTimeout(() => {
        target.selectionStart = target.selectionEnd = start + 4;
      }, 0);
    }
  }

  async function handleKill() {
    setShowKillConfirm(true);
  }

  async function confirmKill() {
    setShowKillConfirm(false);
    await deleteSandbox(sandboxId);
    toast("sandbox terminated", "info");
    router.push("/sandboxes");
  }

  function copyOutput() {
    const textEntries = history
      .filter((h) => h.type === "output" || h.type === "error")
      .map((h) => h.text)
      .join("\n\n");
    navigator.clipboard.writeText(textEntries);
    setCopied(true);
    toast("output copied to clipboard", "success");
    setTimeout(() => setCopied(false), 2000);
  }

  function downloadOutput() {
    const textEntries = history
      .map((h) => {
        if (h.type === "input") return `In: ${h.text}`;
        if (h.type === "output") return `Out: ${h.text}`;
        if (h.type === "error") return `Error: ${h.text}`;
        if (h.type === "system") return `# ${h.text}`;
        return "";
      })
      .join("\n\n");
    const blob = new Blob([textEntries], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `sandbox-${sandboxId.slice(0, 8)}-${Date.now()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    toast("output downloaded", "success");
  }

  if (error) {
    return (
      <div className="p-8 animate-fade-in">
        <button
          onClick={() => router.push("/sandboxes")}
          className="flex items-center gap-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] mb-4 tracking-wider"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> back
        </button>
        <div className="p-4 border border-[var(--color-error)]/30 bg-[var(--color-error)]/5">
          <p className="text-xs text-[var(--color-error)]">{error}</p>
        </div>
      </div>
    );
  }

  if (!sandbox) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-dim)]" />
      </div>
    );
  }

  const budgetPct = sandbox.budget_usd > 0 ? (sandbox.budget_used / sandbox.budget_usd) * 100 : 0;
  const inputCount = history.filter(h => h.type === "input").length;

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-[var(--color-border)] bg-[var(--color-bg-card)] flex-shrink-0">
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.push("/sandboxes")}
            className="p-1.5 text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
          </button>
          <div>
            <Breadcrumb items={[
              { label: "sandboxes", href: "/sandboxes" },
              { label: sandbox.label || sandbox.id.slice(0, 8) },
            ]} />
            <h1 className="text-xs font-medium tracking-wide">
              {sandbox.label || sandbox.id.slice(0, 8)}
            </h1>
            <div className="flex items-center gap-3 text-[12px] text-[var(--color-text-dim)] tracking-wider">
              <span className="flex items-center gap-1.5">
                <StatusDot
                  status={sandbox.status === "running" ? "healthy" : sandbox.status === "error" ? "error" : "idle"}
                  size={4}
                  pulse={sandbox.status === "running"}
                />
                {sandbox.status}
              </span>
              {sandbox.vm_id && (
                <span className="flex items-center gap-1">
                  <Cpu className="w-3 h-3" strokeWidth={1.5} />
                  <code className="text-[11px]">{sandbox.vm_id}</code>
                </span>
              )}
              {sandbox.connection_name && (
                <span className="flex items-center gap-1">
                  <Database className="w-3 h-3" strokeWidth={1.5} />
                  {sandbox.connection_name}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Budget indicator */}
          <div className="flex items-center gap-2">
            <DollarSign className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <div className="w-20">
              <div className="flex justify-between text-[11px] text-[var(--color-text-dim)] mb-0.5 tabular-nums">
                <span>${sandbox.budget_used.toFixed(4)}</span>
                <span>${sandbox.budget_usd.toFixed(2)}</span>
              </div>
              <MiniBar
                value={budgetPct}
                max={100}
                width={80}
                height={4}
                color={budgetPct > 80 ? "var(--color-error)" : budgetPct > 50 ? "var(--color-warning)" : "var(--color-success)"}
              />
            </div>
          </div>

          <div className="h-3 w-px bg-[var(--color-border)]" />

          <span className="flex items-center gap-1 text-[12px] text-[var(--color-text-dim)] tracking-wider">
            <Shield className="w-3 h-3 text-[var(--color-success)]" strokeWidth={1.5} />
            {sandbox.row_limit.toLocaleString()}
          </span>

          {sandbox.uptime_sec != null && sandbox.uptime_sec > 0 && (
            <span className="flex items-center gap-1 text-[12px] text-[var(--color-text-dim)] tabular-nums tracking-wider">
              <Clock className="w-3 h-3" strokeWidth={1.5} />
              {sandbox.uptime_sec < 60 ? `${sandbox.uptime_sec.toFixed(0)}s` : `${(sandbox.uptime_sec / 60).toFixed(0)}m`}
            </span>
          )}

          <div className="h-3 w-px bg-[var(--color-border)]" />

          <button
            onClick={copyOutput}
            className="p-1.5 text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
            title="Copy output"
          >
            {copied ? <Check className="w-3 h-3 text-[var(--color-success)]" /> : <Copy className="w-3 h-3" />}
          </button>
          <button
            onClick={downloadOutput}
            className="p-1.5 text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
            title="Download"
          >
            <Download className="w-3 h-3" />
          </button>
          <button
            onClick={() => setExpanded(!expanded)}
            className="p-1.5 text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
          >
            {expanded ? <Minimize2 className="w-3 h-3" /> : <Maximize2 className="w-3 h-3" />}
          </button>
          <button
            onClick={handleKill}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-error)] hover:bg-[var(--color-error)]/5 transition-colors tracking-wider uppercase"
          >
            <Trash2 className="w-3 h-3" /> kill
          </button>
        </div>
      </div>

      {/* Terminal status bar */}
      <div className="flex items-center gap-4 px-4 py-1.5 border-b border-[var(--color-border)] bg-[var(--color-bg)] text-[11px] text-[var(--color-text-dim)] tracking-wider flex-shrink-0">
        <span className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 ${sandbox.status === "running" ? "bg-[var(--color-success)]" : "bg-[var(--color-text-dim)]"}`} />
          {sandbox.status}
        </span>
        <span className="tabular-nums">{inputCount} cells</span>
        <span className="tabular-nums">{history.filter(h => h.type === "error").length} errors</span>
        {sandbox.boot_ms != null && (
          <span className="tabular-nums">boot: {sandbox.boot_ms.toFixed(0)}ms</span>
        )}
        <span className="ml-auto tabular-nums">python3 · gvisor</span>
      </div>

      {/* Terminal output */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-auto p-4 font-mono text-xs space-y-2 bg-[var(--color-bg)]"
      >
        {history.map((entry, i) => (
          <div key={i} className="flex gap-2 animate-fade-in">
            {entry.type === "input" && (
              <div className="w-full">
                <div className="flex items-center gap-2 text-[var(--color-text-muted)] mb-0.5">
                  <span className="text-[12px] text-[var(--color-success)] tracking-wider">
                    In [{history.filter((h, j) => j <= i && h.type === "input").length}]:
                  </span>
                </div>
                <CodeBlock code={entry.text} language="python" maxHeight="20rem" />
              </div>
            )}
            {entry.type === "output" && (
              <div className="w-full">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="text-[12px] text-blue-400 tracking-wider">
                    Out [{history.filter((h, j) => j <= i && h.type === "output").length}]:
                  </span>
                  {entry.execution_ms != null && (
                    <span className="text-[12px] text-[var(--color-text-dim)] flex items-center gap-1 tabular-nums tracking-wider">
                      <Clock className="w-2.5 h-2.5" strokeWidth={1.5} />
                      {entry.execution_ms.toFixed(0)}ms
                    </span>
                  )}
                </div>
                <pre className="whitespace-pre-wrap text-[var(--color-text-muted)] text-[13px] leading-relaxed">
                  {entry.text}
                </pre>
              </div>
            )}
            {entry.type === "image" && entry.imageData && (
              <div className="w-full">
                <div className="flex items-center gap-2 mb-1">
                  <ImageIcon className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
                  <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider">image output</span>
                </div>
                <div className="bg-white p-2 inline-block border border-[var(--color-border)]">
                  <img src={entry.imageData} alt="Sandbox output" className="max-w-full max-h-96" />
                </div>
              </div>
            )}
            {entry.type === "html" && entry.htmlContent && (
              <div className="w-full">
                <div className="flex items-center gap-2 mb-1">
                  <FileText className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
                  <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider">dataframe output</span>
                </div>
                <div className="bg-[var(--color-bg-card)] border border-[var(--color-border)] overflow-x-auto max-h-96">
                  <div
                    className="sandbox-html-output text-[13px] [&_table]:w-full [&_table]:text-left [&_th]:px-3 [&_th]:py-2 [&_th]:text-[11px] [&_th]:text-[var(--color-text-dim)] [&_th]:uppercase [&_th]:tracking-widest [&_th]:border-b [&_th]:border-[var(--color-border)] [&_td]:px-3 [&_td]:py-1.5 [&_td]:text-[var(--color-text-muted)] [&_td]:border-b [&_td]:border-[var(--color-border)]/20 [&_tr:hover]:bg-[var(--color-bg-hover)]"
                    dangerouslySetInnerHTML={{ __html: entry.htmlContent }}
                  />
                </div>
              </div>
            )}
            {entry.type === "error" && (
              <div className="w-full">
                <pre className="whitespace-pre-wrap text-[var(--color-error)] bg-[var(--color-error)]/5 p-3 border border-[var(--color-error)]/20 text-[13px] leading-relaxed">
                  {entry.text}
                </pre>
              </div>
            )}
            {entry.type === "system" && (
              <div className="w-full text-[12px] text-[var(--color-text-dim)] py-1 tracking-wider border-l-2 border-[var(--color-border)] pl-3">
                {entry.text}
              </div>
            )}
          </div>
        ))}
        {running && (
          <div className="flex items-center gap-2 text-[var(--color-text-dim)] text-[12px] py-2 tracking-wider">
            <Loader2 className="w-3 h-3 animate-spin" />
            <span>executing in isolated gvisor sandbox...</span>
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="border-t border-[var(--color-border)] bg-[var(--color-bg-card)] flex-shrink-0">
        {/* Snippet bar */}
        <div className="flex items-center gap-2 px-4 pt-3 pb-1">
          <button
            onClick={() => setShowSnippets(!showSnippets)}
            className="flex items-center gap-1 text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text-muted)] transition-colors tracking-wider"
          >
            {showSnippets ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            snippets
          </button>
          {showSnippets &&
            EXAMPLE_SNIPPETS.map((snippet, idx) => (
              <button
                key={idx}
                onClick={() => setCode(snippet.code)}
                className="px-2 py-0.5 text-[11px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider"
              >
                {snippet.label}
              </button>
            ))}
          <div className="flex-1" />
          <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider tabular-nums">
            [{inputCount}] cells executed
          </span>
        </div>

        <div className="flex gap-3 p-4 pt-2">
          <div className="flex-1 relative">
            {/* Input prompt indicator */}
            <div className="absolute left-3 top-3 text-[12px] text-[var(--color-success)] tracking-wider pointer-events-none select-none">
              In [{inputCount + 1}]:
            </div>
            <textarea
              ref={textareaRef}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="python3"
              rows={expanded ? 12 : 4}
              spellCheck={false}
              className="w-full pl-20 pr-4 py-3 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs font-mono focus:outline-none focus:border-[var(--color-text-dim)] resize-none placeholder:text-[var(--color-text-dim)] leading-relaxed tracking-wide"
              autoFocus
            />
          </div>
          <div className="flex flex-col gap-2 self-end">
            <button
              onClick={handleExecute}
              disabled={running || !code.trim()}
              className="flex items-center gap-2 px-5 py-3 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
            >
              {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
              run
              <kbd className="ml-1 px-1 py-0.5 bg-[var(--color-bg)]/20 text-[7px] opacity-50 border border-[var(--color-bg)]/30">
                ⌃⏎
              </kbd>
            </button>
          </div>
        </div>
        <div className="flex items-center justify-between px-4 pb-3">
          <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider">
            isolated gvisor sandbox · ctrl+enter to execute · tab to indent
          </p>
          {code.length > 0 && (
            <span className="text-[11px] text-[var(--color-text-dim)] tabular-nums tracking-wider">
              {code.length} chars / {code.split("\n").length} lines
            </span>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={showKillConfirm}
        title="kill sandbox"
        message="Terminate this sandbox? Any running processes will be killed and unsaved state will be lost."
        confirmLabel="kill"
        variant="danger"
        onConfirm={confirmKill}
        onCancel={() => setShowKillConfirm(false)}
      />
    </div>
  );
}
