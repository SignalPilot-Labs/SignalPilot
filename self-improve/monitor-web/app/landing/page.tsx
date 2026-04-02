"use client";

import { useState, useEffect, useRef } from "react";
import { motion, useInView } from "framer-motion";
import Image from "next/image";

/* ─── Animated counter ─── */
function Counter({ target, suffix = "" }: { target: number; suffix?: string }) {
  const [count, setCount] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });

  useEffect(() => {
    if (!inView) return;
    let frame: number;
    const duration = 1200;
    const start = performance.now();
    const step = (now: number) => {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setCount(Math.floor(eased * target));
      if (progress < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [inView, target]);

  return (
    <span ref={ref}>
      {count.toLocaleString()}
      {suffix}
    </span>
  );
}

/* ─── Typing effect ─── */
function TypingText({ text, delay = 0 }: { text: string; delay?: number }) {
  const [displayed, setDisplayed] = useState("");
  const [started, setStarted] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });

  useEffect(() => {
    if (!inView) return;
    const timer = setTimeout(() => setStarted(true), delay);
    return () => clearTimeout(timer);
  }, [inView, delay]);

  useEffect(() => {
    if (!started) return;
    let i = 0;
    const interval = setInterval(() => {
      i++;
      setDisplayed(text.slice(0, i));
      if (i >= text.length) clearInterval(interval);
    }, 30);
    return () => clearInterval(interval);
  }, [started, text]);

  return (
    <span ref={ref}>
      {displayed}
      {displayed.length < text.length && started && (
        <span className="animate-blink text-[var(--color-success)]">▊</span>
      )}
    </span>
  );
}

/* ─── Grid background SVG ─── */
function GridBG() {
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      <svg width="100%" height="100%" className="opacity-[0.03]">
        <defs>
          <pattern id="grid" width="48" height="48" patternUnits="userSpaceOnUse">
            <path d="M 48 0 L 0 0 0 48" fill="none" stroke="white" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid)" />
      </svg>
      {/* Radial fade */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_0%,#050505_70%)]" />
    </div>
  );
}

/* ─── Glow orb ─── */
function GlowOrb({ className }: { className?: string }) {
  return (
    <div
      className={`absolute rounded-full blur-[120px] pointer-events-none ${className}`}
      style={{ background: "radial-gradient(circle, rgba(0,255,136,0.06) 0%, transparent 70%)" }}
    />
  );
}

/* ─── Section wrapper ─── */
function Section({
  children,
  className = "",
  id,
}: {
  children: React.ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={`relative px-6 md:px-12 lg:px-24 ${className}`}>
      {children}
    </section>
  );
}

/* ─── Agent card ─── */
function AgentCard({
  title,
  role,
  icon,
  tasks,
  delay,
}: {
  title: string;
  role: string;
  icon: React.ReactNode;
  tasks: string[];
  delay: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      transition={{ duration: 0.5, delay }}
      className="group relative border border-[var(--color-border)] bg-[var(--color-bg-card)] p-6 hover:border-[var(--color-border-hover)] transition-all duration-200"
    >
      {/* Top accent line */}
      <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-[rgba(0,255,136,0.3)] to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />

      <div className="flex items-center gap-3 mb-4">
        <div className="flex items-center justify-center w-8 h-8 border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-success)]">
          {icon}
        </div>
        <div>
          <h3 className="text-[13px] font-semibold text-[var(--color-accent)]">{title}</h3>
          <p className="text-[10px] text-[var(--color-text-muted)] uppercase tracking-wider">{role}</p>
        </div>
      </div>

      <ul className="space-y-2">
        {tasks.map((task, i) => (
          <li key={i} className="flex items-start gap-2 text-[11px] text-[var(--color-text-muted)]">
            <span className="text-[var(--color-text-dim)] mt-0.5 shrink-0">→</span>
            {task}
          </li>
        ))}
      </ul>
    </motion.div>
  );
}

/* ─── Logo item ─── */
function LogoItem({ src, alt }: { src: string; alt: string }) {
  return (
    <div className="flex items-center justify-center h-12 w-24 opacity-40 hover:opacity-80 transition-opacity duration-200 grayscale hover:grayscale-0">
      <Image src={src} alt={alt} width={80} height={32} className="object-contain max-h-8" />
    </div>
  );
}

/* ─── Feature row ─── */
function Feature({
  title,
  description,
  code,
  delay,
}: {
  title: string;
  description: string;
  code: string;
  delay: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      transition={{ duration: 0.4, delay }}
      className="grid grid-cols-1 md:grid-cols-2 gap-6 py-8 border-b border-[var(--color-border)]"
    >
      <div className="flex flex-col justify-center">
        <h3 className="text-[14px] font-semibold text-[var(--color-accent)] mb-2">{title}</h3>
        <p className="text-[12px] text-[var(--color-text-muted)] leading-relaxed">{description}</p>
      </div>
      <div className="bg-[rgba(0,0,0,0.4)] border border-[var(--color-border)] p-4 font-mono text-[11px] text-[var(--color-text-muted)] overflow-x-auto">
        <pre className="whitespace-pre">{code}</pre>
      </div>
    </motion.div>
  );
}

/* ════════════════════════════════════════════════════════════════════
   LANDING PAGE
   ════════════════════════════════════════════════════════════════════ */

const logos = [
  { src: "/logos/anthropic-logo.svg", alt: "Anthropic" },
  { src: "/logos/claudecode.svg", alt: "Claude Code" },
  { src: "/logos/cursor.svg", alt: "Cursor" },
  { src: "/logos/vscode.svg", alt: "VS Code" },
  { src: "/logos/Databricks.svg", alt: "Databricks" },
  { src: "/logos/snowflake-color.png", alt: "Snowflake" },
  { src: "/logos/Dbt-Icon.svg", alt: "dbt" },
  { src: "/logos/linear-light-logo.svg", alt: "Linear" },
  { src: "/logos/jira-1.svg", alt: "Jira" },
  { src: "/logos/slack-new-logo.svg", alt: "Slack" },
  { src: "/logos/jupyter_logo_icon.svg", alt: "Jupyter" },
  { src: "/logos/stripe-payment-icon.svg", alt: "Stripe" },
  { src: "/logos/yc.svg", alt: "Y Combinator" },
];

export default function LandingPage() {
  const [scrollY, setScrollY] = useState(0);

  useEffect(() => {
    const handleScroll = () => setScrollY(window.scrollY);
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <div className="min-h-screen bg-[var(--color-bg)] text-[var(--color-text)] overflow-x-hidden">
      {/* ─── Nav ─── */}
      <nav className="fixed top-0 left-0 right-0 z-50 border-b border-[var(--color-border)] bg-[var(--color-bg)]/80 backdrop-blur-md">
        <div className="flex items-center justify-between px-6 md:px-12 lg:px-24 h-12">
          <div className="flex items-center gap-2.5">
            <svg width="16" height="16" viewBox="0 0 14 14" fill="none" stroke="#00ff88" strokeWidth="1.5" strokeLinecap="round">
              <path d="M2 10L5 4L7 7L9 3L12 10" />
            </svg>
            <span className="text-[13px] font-bold tracking-tight">SignalPilot</span>
            <span className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] ml-1">Self-Improve</span>
          </div>
          <div className="flex items-center gap-6">
            <a href="#agents" className="text-[11px] text-[var(--color-text-muted)] hover:text-[var(--color-accent)] transition-colors">Agents</a>
            <a href="#features" className="text-[11px] text-[var(--color-text-muted)] hover:text-[var(--color-accent)] transition-colors">Features</a>
            <a href="#stack" className="text-[11px] text-[var(--color-text-muted)] hover:text-[var(--color-accent)] transition-colors">Stack</a>
            <a
              href="/"
              className="text-[11px] px-3 py-1.5 border border-[var(--color-border)] hover:border-[var(--color-border-hover)] text-[var(--color-accent)] transition-all hover:bg-[var(--color-bg-hover)]"
            >
              Open Monitor →
            </a>
          </div>
        </div>
      </nav>

      {/* ─── Hero ─── */}
      <Section className="pt-32 pb-24 min-h-[90vh] flex flex-col justify-center">
        <GridBG />
        <GlowOrb className="w-[600px] h-[600px] top-[-200px] left-[-200px]" />
        <GlowOrb className="w-[400px] h-[400px] bottom-[-100px] right-[-100px]" />

        <div className="relative z-10 max-w-4xl">
          {/* Tag */}
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="inline-flex items-center gap-2 mb-6 px-3 py-1 border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[10px] text-[var(--color-text-muted)] uppercase tracking-wider"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-success)] animate-pulse-dot" />
            Autonomous improvement loop
          </motion.div>

          {/* Headline */}
          <motion.h1
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.1 }}
            className="text-[clamp(32px,5vw,56px)] font-bold leading-[1.1] tracking-tight text-[var(--color-accent)] mb-6"
          >
            Software that
            <br />
            <span className="text-[var(--color-success)]">improves itself.</span>
          </motion.h1>

          {/* Subheadline */}
          <motion.p
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className="text-[14px] md:text-[16px] text-[var(--color-text-muted)] leading-relaxed max-w-xl mb-10"
          >
            CEO, PM, and Engineer agents collaborate in an autonomous loop —
            planning improvements, writing code, running tests, and shipping PRs.
            Every cycle makes your codebase better.
          </motion.p>

          {/* CTA row */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="flex items-center gap-4 mb-16"
          >
            <a
              href="/"
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-white text-black text-[12px] font-semibold hover:bg-[var(--color-accent-hover)] transition-colors"
            >
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
                <polygon points="3 2 8 5 3 8" />
              </svg>
              Launch Monitor
            </a>
            <a
              href="#agents"
              className="inline-flex items-center gap-2 px-5 py-2.5 border border-[var(--color-border)] text-[12px] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-accent)] transition-all"
            >
              How it works
            </a>
          </motion.div>

          {/* Terminal block */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.4 }}
            className="border border-[var(--color-border)] bg-[rgba(0,0,0,0.5)] max-w-2xl"
          >
            {/* Terminal header */}
            <div className="flex items-center gap-2 px-4 py-2 border-b border-[var(--color-border)]">
              <div className="flex gap-1.5">
                <div className="w-2 h-2 rounded-full bg-[#ff5f57]" />
                <div className="w-2 h-2 rounded-full bg-[#febc2e]" />
                <div className="w-2 h-2 rounded-full bg-[#28c840]" />
              </div>
              <span className="text-[9px] text-[var(--color-text-dim)] ml-2 uppercase tracking-wider">self-improve — agent loop</span>
            </div>
            {/* Terminal body */}
            <div className="p-4 font-mono text-[11px] leading-relaxed space-y-1">
              <div className="text-[var(--color-text-dim)]">
                <span className="text-[var(--color-success)]">$</span>{" "}
                <TypingText text="signalpilot improve --mode autonomous" delay={600} />
              </div>
              <div className="text-[var(--color-text-dim)] mt-2">
                <span className="text-[#555]">{">"}</span> <span className="text-[var(--color-text-muted)]">CEO Agent</span> analyzing codebase...
              </div>
              <div className="text-[var(--color-text-dim)]">
                <span className="text-[#555]">{">"}</span> <span className="text-[var(--color-text-muted)]">PM Agent</span> prioritizing 12 improvements
              </div>
              <div className="text-[var(--color-text-dim)]">
                <span className="text-[#555]">{">"}</span> <span className="text-[var(--color-text-muted)]">Engineer Agent</span> implementing changes
              </div>
              <div className="text-[var(--color-text-dim)]">
                <span className="text-[#555]">{">"}</span> Running tests... <span className="text-[var(--color-success)]">✓ 47/47 passed</span>
              </div>
              <div className="text-[var(--color-text-dim)]">
                <span className="text-[#555]">{">"}</span> PR created: <span className="text-[#88ccff]">improvements-round-2026-04-02</span>
              </div>
              <div className="text-[var(--color-success)] mt-1">
                ✓ Round complete — 8 files changed, 3 features added
              </div>
            </div>
          </motion.div>
        </div>
      </Section>

      {/* ─── Stats bar ─── */}
      <Section className="py-12 border-y border-[var(--color-border)]">
        <div className="relative z-10 grid grid-cols-2 md:grid-cols-4 gap-8 max-w-4xl mx-auto text-center">
          {[
            { value: 247, suffix: "+", label: "PRs shipped" },
            { value: 1842, suffix: "", label: "Files improved" },
            { value: 99, suffix: "%", label: "Test pass rate" },
            { value: 24, suffix: "/7", label: "Autonomous" },
          ].map((stat, i) => (
            <motion.div
              key={stat.label}
              initial={{ opacity: 0, y: 8 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.4, delay: i * 0.1 }}
            >
              <div className="text-[28px] font-bold text-[var(--color-accent)] tabular-nums">
                <Counter target={stat.value} suffix={stat.suffix} />
              </div>
              <div className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-wider mt-1">
                {stat.label}
              </div>
            </motion.div>
          ))}
        </div>
      </Section>

      {/* ─── Backed by ─── */}
      <Section className="py-10">
        <div className="relative z-10 flex items-center justify-center gap-10 opacity-40">
          <span className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-[0.2em]">Backed by</span>
          <Image src="/logos/yc.svg" alt="Y Combinator" width={24} height={24} className="grayscale" />
          <Image src="/logos/anthropic-logo.svg" alt="Anthropic" width={80} height={20} className="grayscale" />
          <Image src="/logos/goldman.svg" alt="Goldman Sachs" width={24} height={24} className="grayscale" />
        </div>
      </Section>

      {/* ─── Agent Architecture ─── */}
      <Section id="agents" className="py-24">
        <div className="relative z-10 max-w-5xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="mb-12"
          >
            <p className="text-[10px] text-[var(--color-success)] uppercase tracking-[0.2em] mb-2">Architecture</p>
            <h2 className="text-[28px] font-bold text-[var(--color-accent)] tracking-tight">
              Three agents. One loop.
            </h2>
            <p className="text-[13px] text-[var(--color-text-muted)] mt-3 max-w-lg">
              Inspired by how the best companies operate — a CEO sets direction,
              a PM prioritizes, and engineers execute. Continuously.
            </p>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <AgentCard
              title="CEO Agent"
              role="Strategic Direction"
              delay={0}
              icon={
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
                  <circle cx="7" cy="4" r="2.5" />
                  <path d="M2 12c0-2.8 2.2-5 5-5s5 2.2 5 5" />
                </svg>
              }
              tasks={[
                "Analyzes codebase health and priorities",
                "Sets improvement direction each cycle",
                "Reviews shipped PRs for quality",
                "Adjusts strategy based on outcomes",
              ]}
            />
            <AgentCard
              title="PM Agent"
              role="Prioritization & Planning"
              delay={0.1}
              icon={
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
                  <rect x="2" y="2" width="10" height="10" rx="1" />
                  <path d="M5 5h4M5 7h4M5 9h2" />
                </svg>
              }
              tasks={[
                "Breaks strategy into actionable tasks",
                "Prioritizes by impact and effort",
                "Creates detailed implementation specs",
                "Tracks progress across improvement rounds",
              ]}
            />
            <AgentCard
              title="Engineer Agent"
              role="Implementation & Shipping"
              delay={0.2}
              icon={
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
                  <path d="M4 4L1 7l3 3M10 4l3 3-3 3M8 2l-2 10" />
                </svg>
              }
              tasks={[
                "Writes production-grade code changes",
                "Runs test suites and validates",
                "Creates atomic, well-scoped commits",
                "Ships PRs with clear descriptions",
              ]}
            />
          </div>

          {/* Loop visualization */}
          <motion.div
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6, delay: 0.3 }}
            className="mt-12 flex items-center justify-center gap-3 text-[11px] text-[var(--color-text-dim)]"
          >
            {["Analyze", "Plan", "Implement", "Test", "Ship", "Review"].map((step, i) => (
              <div key={step} className="flex items-center gap-3">
                <span className="px-3 py-1.5 border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-accent)] transition-all cursor-default">
                  {step}
                </span>
                {i < 5 && (
                  <svg width="12" height="8" viewBox="0 0 12 8" fill="none" stroke="currentColor" strokeWidth="1" className="text-[var(--color-text-dim)]">
                    <path d="M0 4h10M8 1l3 3-3 3" />
                  </svg>
                )}
              </div>
            ))}
            {/* Loop arrow */}
            <svg width="24" height="16" viewBox="0 0 24 16" fill="none" stroke="var(--color-success)" strokeWidth="1" className="ml-1 opacity-50">
              <path d="M20 8c0-3-2-6-8-6S2 5 2 8M4 5L2 8l3 2" />
            </svg>
          </motion.div>
        </div>
      </Section>

      {/* ─── Architecture Diagram ─── */}
      <Section className="py-20 border-t border-[var(--color-border)]">
        <div className="relative z-10 max-w-4xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="mb-8 text-center"
          >
            <p className="text-[10px] text-[var(--color-success)] uppercase tracking-[0.2em] mb-2">System Design</p>
            <h2 className="text-[20px] font-bold text-[var(--color-accent)] tracking-tight">
              End-to-end architecture
            </h2>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, scale: 0.98 }}
            whileInView={{ opacity: 1, scale: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6 }}
            className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-8"
          >
            <svg viewBox="0 0 800 320" fill="none" className="w-full" style={{ fontFamily: "monospace" }}>
              {/* Grid background */}
              <defs>
                <pattern id="arch-grid" width="20" height="20" patternUnits="userSpaceOnUse">
                  <path d="M 20 0 L 0 0 0 20" fill="none" stroke="white" strokeWidth="0.3" opacity="0.05" />
                </pattern>
              </defs>
              <rect width="800" height="320" fill="url(#arch-grid)" />

              {/* CEO Agent */}
              <rect x="30" y="40" width="160" height="80" stroke="#333" fill="#0a0a0a" strokeWidth="1" />
              <rect x="30" y="40" width="160" height="1" fill="#00ff88" opacity="0.4" />
              <circle cx="55" cy="70" r="8" stroke="#00ff88" strokeWidth="1" fill="none" opacity="0.5" />
              <text x="70" y="74" fill="#e8e8e8" fontSize="11" fontWeight="600">CEO Agent</text>
              <text x="50" y="100" fill="#555" fontSize="9">Strategy · Review · Direct</text>

              {/* Arrow CEO → PM */}
              <line x1="190" y1="80" x2="280" y2="80" stroke="#333" strokeWidth="1" strokeDasharray="4 3">
                <animate attributeName="stroke-dashoffset" from="7" to="0" dur="1s" repeatCount="indefinite" />
              </line>
              <polygon points="280,76 280,84 290,80" fill="#555" />
              <text x="220" y="72" fill="#444" fontSize="8">delegate</text>

              {/* PM Agent */}
              <rect x="290" y="40" width="160" height="80" stroke="#333" fill="#0a0a0a" strokeWidth="1" />
              <rect x="290" y="40" width="160" height="1" fill="#00ff88" opacity="0.4" />
              <rect cx="315" cy="70" x="307" y="62" width="16" height="16" stroke="#00ff88" strokeWidth="1" fill="none" opacity="0.5" />
              <text x="330" y="74" fill="#e8e8e8" fontSize="11" fontWeight="600">PM Agent</text>
              <text x="310" y="100" fill="#555" fontSize="9">Plan · Prioritize · Spec</text>

              {/* Arrow PM → Engineer */}
              <line x1="450" y1="80" x2="540" y2="80" stroke="#333" strokeWidth="1" strokeDasharray="4 3">
                <animate attributeName="stroke-dashoffset" from="7" to="0" dur="1s" repeatCount="indefinite" />
              </line>
              <polygon points="540,76 540,84 550,80" fill="#555" />
              <text x="478" y="72" fill="#444" fontSize="8">tasks</text>

              {/* Engineer Agent */}
              <rect x="550" y="40" width="200" height="80" stroke="#333" fill="#0a0a0a" strokeWidth="1" />
              <rect x="550" y="40" width="200" height="1" fill="#00ff88" opacity="0.4" />
              <text x="580" y="66" fill="#00ff88" fontSize="10" opacity="0.7">&lt;/&gt;</text>
              <text x="605" y="74" fill="#e8e8e8" fontSize="11" fontWeight="600">Engineer Agent</text>
              <text x="570" y="100" fill="#555" fontSize="9">Code · Test · Commit · Ship</text>

              {/* Tools layer */}
              <rect x="550" y="160" width="200" height="60" stroke="#333" fill="#0a0a0a" strokeWidth="1" rx="0" />
              <text x="570" y="185" fill="#777" fontSize="9">Edit · Bash · Grep · Read</text>
              <text x="570" y="200" fill="#777" fontSize="9">Write · Agent · Git · Test</text>

              {/* Arrow Engineer → Tools */}
              <line x1="650" y1="120" x2="650" y2="160" stroke="#333" strokeWidth="1" />
              <polygon points="646,160 654,160 650,168" fill="#555" />

              {/* Git/GitHub */}
              <rect x="550" y="250" width="200" height="50" stroke="#333" fill="#0a0a0a" strokeWidth="1" />
              <rect x="550" y="299" width="200" height="1" fill="#00ff88" opacity="0.3" />
              <text x="620" y="278" fill="#e8e8e8" fontSize="10" textAnchor="middle">GitHub</text>
              <text x="660" y="278" fill="#555" fontSize="9">· PRs · Branches</text>

              {/* Arrow Tools → Git */}
              <line x1="650" y1="220" x2="650" y2="250" stroke="#333" strokeWidth="1" />
              <polygon points="646,250 654,250 650,258" fill="#555" />

              {/* Monitor */}
              <rect x="30" y="160" width="180" height="100" stroke="#333" fill="#0a0a0a" strokeWidth="1" />
              <rect x="30" y="160" width="180" height="1" fill="#88ccff" opacity="0.3" />
              <text x="85" y="195" fill="#e8e8e8" fontSize="11" fontWeight="600">Monitor</text>
              <text x="55" y="215" fill="#555" fontSize="9">Real-time event stream</text>
              <text x="55" y="230" fill="#555" fontSize="9">Tool calls · Audit · Stats</text>
              <text x="55" y="245" fill="#555" fontSize="9">SSE · WebSocket</text>

              {/* Arrow Agents → Monitor (observability) */}
              <line x1="290" y1="120" x2="210" y2="160" stroke="#333" strokeWidth="1" strokeDasharray="2 4" opacity="0.5" />
              <line x1="550" y1="120" x2="210" y2="180" stroke="#333" strokeWidth="1" strokeDasharray="2 4" opacity="0.5" />
              <text x="300" y="150" fill="#444" fontSize="8">observe</text>

              {/* Session gate */}
              <rect x="290" y="160" width="180" height="60" stroke="#333" fill="#0a0a0a" strokeWidth="1" />
              <rect x="290" y="160" width="180" height="1" fill="#ffaa00" opacity="0.3" />
              <text x="337" y="195" fill="#e8e8e8" fontSize="10" fontWeight="600">Session Gate</text>
              <text x="310" y="208" fill="#555" fontSize="8">Time lock · Budget · Permissions</text>

              {/* Arrow Session Gate → Engineer */}
              <line x1="470" y1="180" x2="550" y2="120" stroke="#333" strokeWidth="1" strokeDasharray="2 4" opacity="0.5" />
              <text x="505" y="145" fill="#444" fontSize="8">guard</text>

              {/* Loop arrow from GitHub back to CEO */}
              <path d="M550 275 L30 275 L30 120" stroke="#00ff88" strokeWidth="1" fill="none" opacity="0.2" strokeDasharray="6 4">
                <animate attributeName="stroke-dashoffset" from="10" to="0" dur="2s" repeatCount="indefinite" />
              </path>
              <polygon points="26,120 34,120 30,112" fill="#00ff88" opacity="0.3" />
              <text x="260" y="290" fill="#00ff88" fontSize="9" opacity="0.4" textAnchor="middle">feedback loop</text>
            </svg>
          </motion.div>
        </div>
      </Section>

      {/* ─── Features ─── */}
      <Section id="features" className="py-24 border-t border-[var(--color-border)]">
        <div className="relative z-10 max-w-4xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="mb-8"
          >
            <p className="text-[10px] text-[var(--color-success)] uppercase tracking-[0.2em] mb-2">Capabilities</p>
            <h2 className="text-[28px] font-bold text-[var(--color-accent)] tracking-tight">
              Built for production.
            </h2>
          </motion.div>

          <Feature
            title="Autonomous Git Workflow"
            description="Creates branches, makes atomic commits, opens PRs, and responds to review feedback. Full git lifecycle without human intervention."
            code={`// Agent creates improvement branch
git checkout -b improvements-round-2026-04-02

// Makes scoped, atomic commits
git commit -m "Add connection pooling
  to reduce latency by 40%"

// Opens PR with context
gh pr create --title "Perf: connection pooling"
  --body "## Why\\nReduce p99 latency..."`}
            delay={0}
          />
          <Feature
            title="Real-time Monitoring"
            description="Watch every tool call, file edit, and decision in real-time through the monitor dashboard. Full observability into the agent's reasoning."
            code={`GET /api/runs/:id/events
Content-Type: text/event-stream

data: {"kind":"tool","name":"Edit",
  "file":"src/db/pool.ts","line":42}
data: {"kind":"tool","name":"Bash",
  "cmd":"npm test -- --coverage"}
data: {"kind":"audit","type":"commit",
  "sha":"a1b2c3d"}`}
            delay={0.1}
          />
          <Feature
            title="Session-Gated Safety"
            description="Time-locked sessions with budget controls, permission boundaries, and kill switches. The agent operates within strict guardrails you define."
            code={`{
  "session": {
    "time_lock": "30m",
    "cost_budget": 5.00,
    "branch_pattern": "improvements-*",
    "blocked_paths": [".env", "secrets/"],
    "require_tests": true,
    "auto_pr": true
  }
}`}
            delay={0.2}
          />
          <Feature
            title="Claude Agent SDK"
            description="Powered by the Claude Agent SDK with tool-use, sub-agents, and structured reasoning. Each agent has specialized tools and system prompts."
            code={`from claude_agent_sdk import Agent

ceo = Agent(
  model="claude-opus-4-6",
  tools=[analyze, review, prioritize],
  system=load("prompts/ceo.md")
)

# CEO delegates to PM and Engineer
result = await ceo.run(
  "Improve the SignalPilot codebase"
)`}
            delay={0.3}
          />
        </div>
      </Section>

      {/* ─── Integration logos ─── */}
      <Section id="stack" className="py-20 border-t border-[var(--color-border)]">
        <div className="relative z-10 max-w-4xl mx-auto text-center">
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
          >
            <p className="text-[10px] text-[var(--color-success)] uppercase tracking-[0.2em] mb-2">Integrations</p>
            <h2 className="text-[20px] font-bold text-[var(--color-accent)] tracking-tight mb-2">
              Works with your stack.
            </h2>
            <p className="text-[12px] text-[var(--color-text-muted)] mb-10">
              Connects to the tools and infrastructure you already use.
            </p>
          </motion.div>

          <motion.div
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6 }}
            className="flex flex-wrap items-center justify-center gap-8"
          >
            {logos.map((logo) => (
              <LogoItem key={logo.alt} src={logo.src} alt={logo.alt} />
            ))}
          </motion.div>
        </div>
      </Section>

      {/* ─── How it works (GStacks-style vertical) ─── */}
      <Section className="py-24 border-t border-[var(--color-border)]">
        <div className="relative z-10 max-w-3xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="mb-12"
          >
            <p className="text-[10px] text-[var(--color-success)] uppercase tracking-[0.2em] mb-2">Process</p>
            <h2 className="text-[28px] font-bold text-[var(--color-accent)] tracking-tight">
              How a round works.
            </h2>
          </motion.div>

          <div className="relative">
            {/* Vertical line */}
            <div className="absolute left-[15px] top-0 bottom-0 w-px bg-[var(--color-border)]" />

            {[
              {
                step: "01",
                title: "CEO scans the codebase",
                desc: "Reads recent commits, open issues, test results, and code quality metrics to understand current state.",
              },
              {
                step: "02",
                title: "PM creates a task list",
                desc: "Breaks the CEO's strategy into discrete, prioritized tasks with clear acceptance criteria.",
              },
              {
                step: "03",
                title: "Engineer implements changes",
                desc: "Writes code, runs tests, and makes atomic commits. Uses sub-agents for parallel file exploration.",
              },
              {
                step: "04",
                title: "Tests validate everything",
                desc: "Full test suite runs against changes. Failing tests are automatically investigated and fixed.",
              },
              {
                step: "05",
                title: "PR ships with full context",
                desc: "A pull request is created with a summary of changes, test results, and the reasoning behind each decision.",
              },
              {
                step: "06",
                title: "Loop repeats",
                desc: "The CEO reviews outcomes and starts the next round. Each cycle compounds improvements.",
              },
            ].map((item, i) => (
              <motion.div
                key={item.step}
                initial={{ opacity: 0, x: -8 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.4, delay: i * 0.08 }}
                className="relative pl-10 pb-8 last:pb-0"
              >
                {/* Dot */}
                <div className="absolute left-[11px] top-[2px] w-[9px] h-[9px] border border-[var(--color-border-hover)] bg-[var(--color-bg)]" />

                <div className="text-[9px] text-[var(--color-text-dim)] uppercase tracking-wider mb-1">
                  Step {item.step}
                </div>
                <h3 className="text-[13px] font-semibold text-[var(--color-accent)] mb-1">
                  {item.title}
                </h3>
                <p className="text-[11px] text-[var(--color-text-muted)] leading-relaxed">
                  {item.desc}
                </p>
              </motion.div>
            ))}
          </div>
        </div>
      </Section>

      {/* ─── CTA ─── */}
      <Section className="py-24 border-t border-[var(--color-border)]">
        <div className="relative z-10 max-w-2xl mx-auto text-center">
          <GlowOrb className="w-[400px] h-[400px] top-[-100px] left-1/2 -translate-x-1/2" />

          <motion.div
            initial={{ opacity: 0, y: 12 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
          >
            <h2 className="text-[32px] font-bold text-[var(--color-accent)] tracking-tight mb-4">
              Let your codebase
              <br />
              improve overnight.
            </h2>
            <p className="text-[13px] text-[var(--color-text-muted)] mb-8 max-w-md mx-auto">
              Deploy the self-improving agent. Wake up to pull requests
              that make your software better — every single day.
            </p>

            <div className="flex items-center justify-center gap-4">
              <a
                href="/"
                className="inline-flex items-center gap-2 px-6 py-3 bg-white text-black text-[12px] font-semibold hover:bg-[var(--color-accent-hover)] transition-colors"
              >
                Open Monitor Dashboard
              </a>
              <a
                href="https://github.com/nicholasmartin/signalpilot"
                target="_blank"
                rel="noopener"
                className="inline-flex items-center gap-2 px-6 py-3 border border-[var(--color-border)] text-[12px] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-accent)] transition-all"
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z" />
                </svg>
                View Source
              </a>
            </div>
          </motion.div>
        </div>
      </Section>

      {/* ─── Footer ─── */}
      <footer className="border-t border-[var(--color-border)] px-6 md:px-12 lg:px-24 py-8">
        <div className="flex items-center justify-between max-w-5xl mx-auto">
          <div className="flex items-center gap-2">
            <svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="#555" strokeWidth="1.5" strokeLinecap="round">
              <path d="M2 10L5 4L7 7L9 3L12 10" />
            </svg>
            <span className="text-[10px] text-[var(--color-text-dim)]">
              SignalPilot · Self-Improving Infrastructure
            </span>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-[10px] text-[var(--color-text-dim)]">
              Powered by Claude Agent SDK
            </span>
            <Image src="/logos/anthropic-logo.svg" alt="Anthropic" width={60} height={16} className="opacity-30" />
          </div>
        </div>
      </footer>
    </div>
  );
}
