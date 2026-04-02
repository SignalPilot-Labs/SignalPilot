import {
  Shield,
  Database,
  Eye,
  Lock,
  BarChart3,
  FileText,
  ExternalLink,
  ArrowRight,
  Activity,
} from "lucide-react";
import { CtaFooter } from "./cta-footer";

// ── Nav ─────────────────────────────────────────────────────────────────────

const Nav = () => (
  <nav className="fixed top-0 left-0 right-0 z-50 frosted border-b border-[var(--color-border)]">
    <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
      <a href="#" className="flex items-center gap-2 group">
        <span className="text-xs font-bold tracking-wider text-[var(--color-text)] group-hover:text-white transition-colors">
          SIGNALPILOT
        </span>
        <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-success)] pulse-dot" />
      </a>
      <div className="hidden sm:flex items-center gap-6 text-xs text-[var(--color-text-muted)]">
        <a href="#features" className="hover:text-[var(--color-text)] transition-colors hover-underline">
          Features
        </a>
        <a href="#architecture" className="hover:text-[var(--color-text)] transition-colors hover-underline">
          Architecture
        </a>
        <a href="#pricing" className="hover:text-[var(--color-text)] transition-colors hover-underline">
          Pricing
        </a>
      </div>
      <a
        href="#cta"
        className="text-xs px-3 py-1.5 border border-[var(--color-success)] text-[var(--color-success)] hover:bg-[var(--color-success)] hover:text-black transition-all"
      >
        Get Started
      </a>
    </div>
  </nav>
);

// ── Hero ─────────────────────────────────────────────────────────────────────

const TERMINAL_LINES = [
  { text: "$ signalpilot query --db production", cls: "text-[var(--color-text-dim)]" },
  { text: "> SELECT name, email FROM users WHERE region = 'EU'", cls: "text-[var(--color-text)]" },
  { text: "", cls: "" },
  { text: "┌─ governance pipeline ─────────────────────┐", cls: "text-[var(--color-border-hover)]" },
  { text: "│ ✓ sql_parse ............ 2ms              │", cls: "text-[var(--color-success)]" },
  { text: "│ ✓ policy_check ......... 5ms              │", cls: "text-[var(--color-success)]" },
  { text: "│ ✓ cost_estimate ........ $0.003           │", cls: "text-[var(--color-success)]" },
  { text: "│ ✓ row_limit ............ 1000 rows max    │", cls: "text-[var(--color-success)]" },
  { text: "│ ✓ pii_redact ........... 2 fields masked  │", cls: "text-[var(--color-success)]" },
  { text: "│ ✓ audit_log ............ recorded         │", cls: "text-[var(--color-success)]" },
  { text: "└───────────────────────────────────────────┘", cls: "text-[var(--color-border-hover)]" },
  { text: "", cls: "" },
  { text: "3 rows returned (pii redacted) in 47ms", cls: "text-[var(--color-text-muted)]" },
];

const Hero = () => (
  <section className="relative pt-32 pb-24 px-6 overflow-hidden bg-grid">
    {/* Radial glow */}
    <div
      className="absolute inset-0 pointer-events-none"
      style={{
        background:
          "radial-gradient(ellipse 60% 40% at 50% 0%, rgba(0,255,136,0.04) 0%, transparent 70%)",
      }}
      aria-hidden="true"
    />
    <div className="max-w-6xl mx-auto grid lg:grid-cols-2 gap-16 items-center animate-fade-in">
      {/* Copy */}
      <div className="space-y-6">
        <div className="inline-flex items-center gap-2 border border-[var(--color-border)] px-3 py-1 text-xs text-[var(--color-text-muted)]">
          <Activity size={11} className="text-[var(--color-success)]" />
          <span>Zero-trust AI data access</span>
        </div>
        <h1 className="text-4xl sm:text-5xl font-light leading-tight tracking-tight">
          Governed{" "}
          <span className="text-[var(--color-success)] glow-text font-normal">AI</span>{" "}
          Database{" "}
          <span className="text-[var(--color-success)] glow-text font-normal">Access</span>
        </h1>
        <p className="text-sm text-[var(--color-text-muted)] leading-relaxed max-w-md">
          Every query parsed, validated, sandboxed, and audited.
          Zero trust for AI data access.
        </p>
        <div className="flex flex-wrap gap-3 pt-2">
          <a
            href="#cta"
            className="inline-flex items-center gap-2 px-4 py-2 bg-[var(--color-success)] text-black text-xs font-medium hover:opacity-90 transition-opacity"
          >
            Start Free <ArrowRight size={13} />
          </a>
          <a
            href="#"
            className="inline-flex items-center gap-2 px-4 py-2 border border-[var(--color-border)] text-xs text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all"
          >
            View Docs <ExternalLink size={12} />
          </a>
        </div>
      </div>

      {/* Terminal block */}
      <div className="animate-float">
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] card-glow">
          {/* Terminal chrome */}
          <div className="flex items-center gap-2 px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
            <span className="w-2.5 h-2.5 rounded-full bg-[var(--color-error)] opacity-60" />
            <span className="w-2.5 h-2.5 rounded-full bg-[var(--color-warning)] opacity-60" />
            <span className="w-2.5 h-2.5 rounded-full bg-[var(--color-success)] opacity-60" />
            <span className="ml-2 text-[10px] text-[var(--color-text-dim)] tracking-widest">
              signalpilot — terminal
            </span>
          </div>
          <div className="p-5 space-y-0.5 text-xs leading-relaxed overflow-x-auto">
            {TERMINAL_LINES.map((line, i) => (
              <div key={line.text || `empty-${i}`} className={`whitespace-pre font-mono ${line.cls}`}>
                {line.text || "\u00a0"}
              </div>
            ))}
            <div className="flex items-center gap-0 mt-1">
              <span className="text-[var(--color-text-dim)]">$ </span>
              <span className="w-1.5 h-4 bg-[var(--color-text-dim)] cursor-blink ml-0.5 inline-block" />
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
);

// ── Features ─────────────────────────────────────────────────────────────────

const FEATURES = [
  {
    icon: Shield,
    title: "SQL Governance Engine",
    desc: "Every query is parsed, validated, and policy-checked before execution. Reject unsafe patterns at the gate.",
  },
  {
    icon: Database,
    title: "Multi-Database Support",
    desc: "Connect Postgres, MySQL, SQLite, and more. One governance layer across your entire data estate.",
  },
  {
    icon: Eye,
    title: "PII Redaction",
    desc: "Automatically detect and mask sensitive fields — emails, phone numbers, SSNs — before results leave the sandbox.",
  },
  {
    icon: Lock,
    title: "Sandbox Execution",
    desc: "Queries run inside Firecracker microVMs. Each execution is isolated, time-limited, and resource-capped.",
  },
  {
    icon: BarChart3,
    title: "Cost Budgeting",
    desc: "Set per-query and per-session cost limits. Get real-time estimates before a query hits your database.",
  },
  {
    icon: FileText,
    title: "Full Audit Trail",
    desc: "Every query, every result, every policy decision — immutably logged with timestamps and agent identity.",
  },
];

const Features = () => (
  <section id="features" className="py-24 px-6 bg-dots">
    <div className="max-w-6xl mx-auto space-y-10 animate-fade-in">
      <div className="section-header">
        <span className="text-xs text-[var(--color-text-dim)] tracking-widest">// features</span>
      </div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-px bg-[var(--color-border)] stagger-fade-in">
        {FEATURES.map(({ icon: Icon, title, desc }) => (
          <div
            key={title}
            className="bg-[var(--color-bg-card)] p-6 space-y-3 card-glow card-accent-top card-interactive"
          >
            <Icon size={16} className="text-[var(--color-success)]" />
            <h3 className="text-sm font-medium text-[var(--color-text)]">{title}</h3>
            <p className="text-xs text-[var(--color-text-muted)] leading-relaxed">{desc}</p>
          </div>
        ))}
      </div>
    </div>
  </section>
);

// ── Architecture ─────────────────────────────────────────────────────────────

const PIPELINE = [
  { label: "AI Agent", desc: "MCP client" },
  { label: "Gateway", desc: "Auth & rate limit" },
  { label: "SQL Parser", desc: "AST validation" },
  { label: "Policy Engine", desc: "Rule enforcement" },
  { label: "Firecracker", desc: "Isolated sandbox" },
  { label: "Database", desc: "Postgres / MySQL" },
];

const Architecture = () => (
  <section id="architecture" className="py-24 px-6">
    <div className="max-w-6xl mx-auto space-y-10 animate-fade-in">
      <div className="section-header">
        <span className="text-xs text-[var(--color-text-dim)] tracking-widest">// architecture</span>
      </div>
      <p className="text-xs text-[var(--color-text-muted)] max-w-lg">
        Every AI query passes through six hardened layers before touching your data.
      </p>

      {/* Pipeline diagram */}
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-8">
        {/* Desktop: horizontal flow */}
        <div className="hidden md:flex items-center gap-0 stagger-fade-in">
          {PIPELINE.map((step, i) => (
            <div key={step.label} className="flex items-center flex-1 min-w-0">
              <div className="flex-1 min-w-0">
                <div className="border border-[var(--color-border)] bg-[var(--color-bg)] p-3 card-glow text-center">
                  <div className="text-[10px] font-medium text-[var(--color-text)] truncate">
                    {step.label}
                  </div>
                  <div className="text-[9px] text-[var(--color-text-dim)] mt-0.5 truncate">
                    {step.desc}
                  </div>
                </div>
              </div>
              {i < PIPELINE.length - 1 && (
                <div className="flex items-center shrink-0 w-8">
                  <div className="flex-1 border-t border-dashed border-[var(--color-border-hover)] animate-data-flow" />
                  <svg width="6" height="6" viewBox="0 0 6 6" className="text-[var(--color-border-hover)] shrink-0">
                    <path d="M0 0L6 3L0 6Z" fill="currentColor" />
                  </svg>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Mobile: vertical flow */}
        <div className="flex flex-col gap-0 md:hidden stagger-fade-in">
          {PIPELINE.map((step, i) => (
            <div key={step.label} className="flex flex-col items-center">
              <div className="w-full border border-[var(--color-border)] bg-[var(--color-bg)] px-4 py-3 flex justify-between card-glow">
                <span className="text-xs font-medium text-[var(--color-text)]">{step.label}</span>
                <span className="text-xs text-[var(--color-text-dim)]">{step.desc}</span>
              </div>
              {i < PIPELINE.length - 1 && (
                <div className="flex flex-col items-center py-1">
                  <div className="h-4 border-l border-dashed border-[var(--color-border-hover)]" />
                  <svg width="6" height="6" viewBox="0 0 6 6" className="text-[var(--color-border-hover)] rotate-90">
                    <path d="M0 0L6 3L0 6Z" fill="currentColor" />
                  </svg>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Legend */}
        <div className="mt-6 pt-6 border-t border-[var(--color-border)] flex flex-wrap gap-4 text-[10px] text-[var(--color-text-dim)]">
          <span className="flex items-center gap-1.5">
            <span className="w-4 border-t border-dashed border-[var(--color-border-hover)]" />
            data flow
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 border border-[var(--color-border)]" />
            governance layer
          </span>
          <span className="ml-auto text-[var(--color-success)]">
            all traffic encrypted · TLS 1.3
          </span>
        </div>
      </div>
    </div>
  </section>
);

// ── Stats ─────────────────────────────────────────────────────────────────────

const STATS = [
  { value: "< 50ms", label: "p99 latency" },
  { value: "100%", label: "query audit" },
  { value: "6 layers", label: "governance" },
  { value: "0 trust", label: "architecture" },
];

const Stats = () => (
  <section className="py-20 px-6 border-y border-[var(--color-border)] bg-[var(--color-bg-card)]">
    <div className="max-w-6xl mx-auto">
      <div className="grid grid-cols-2 lg:grid-cols-4 divide-x divide-y lg:divide-y-0 divide-[var(--color-border)] stagger-fade-in">
        {STATS.map(({ value, label }) => (
          <div key={label} className="px-8 py-8 space-y-1 first:pl-0 last:pr-0">
            <div
              className="stat-counter text-3xl sm:text-4xl font-light text-[var(--color-text)] animate-count-up"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {value}
            </div>
            <div className="text-[10px] text-[var(--color-text-dim)] tracking-widest uppercase">
              {label}
            </div>
          </div>
        ))}
      </div>
    </div>
  </section>
);

// ── Page ──────────────────────────────────────────────────────────────────────

export default function LandingPage() {
  return (
    <div className="bg-noise">
      <Nav />
      <main>
        <Hero />
        <Features />
        <Architecture />
        <Stats />
        <CtaFooter />
      </main>
    </div>
  );
}
