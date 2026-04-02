"use client";

import { useState } from "react";
import { Github } from "lucide-react";

export const CtaFooter = () => {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // TODO: Wire to API route for waitlist signup
    if (email.trim()) setSubmitted(true);
  };

  return (
    <footer id="cta" className="relative py-24 px-6 bg-grid">
      {/* Radial glow */}
      <div
        className="absolute pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse 50% 30% at 50% 100%, rgba(0,255,136,0.04) 0%, transparent 70%)",
          inset: 0,
        }}
        aria-hidden="true"
      />

      <div className="max-w-6xl mx-auto space-y-16 animate-fade-in">
        {/* CTA block */}
        <div
          id="pricing"
          className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-10 sm:p-16 text-center space-y-6 card-accent-top"
        >
          <p className="text-[10px] text-[var(--color-text-dim)] tracking-widest uppercase">
            early access
          </p>
          <h2 className="text-2xl sm:text-3xl font-light text-[var(--color-text)]">
            Ready to govern your{" "}
            <span className="text-[var(--color-success)] glow-text">AI data access</span>?
          </h2>
          <p className="text-xs text-[var(--color-text-muted)] max-w-sm mx-auto leading-relaxed">
            Join the waitlist. We onboard teams weekly with white-glove setup support.
          </p>

          {submitted ? (
            <div className="inline-flex items-center gap-2 text-xs text-[var(--color-success)] border border-[rgba(0,255,136,0.2)] px-5 py-3">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-success)]" />
              Request received — we&apos;ll be in touch.
            </div>
          ) : (
            <form
              onSubmit={handleSubmit}
              className="flex flex-col sm:flex-row gap-0 max-w-md mx-auto"
            >
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                className="flex-1 px-4 py-2.5 text-xs bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:outline-none focus:border-[var(--color-border-hover)]"
              />
              <button
                type="submit"
                className="px-5 py-2.5 bg-[var(--color-success)] text-black text-xs font-medium hover:opacity-90 transition-opacity whitespace-nowrap"
              >
                Request Access
              </button>
            </form>
          )}
        </div>

        {/* Footer links */}
        <div className="separator-subtle" />
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 text-[10px] text-[var(--color-text-dim)]">
          <span className="flex items-center gap-2">
            <span className="tracking-wider text-[var(--color-text-muted)]">SIGNALPILOT</span>
            <span className="w-1 h-1 rounded-full bg-[var(--color-success)] pulse-dot" />
            <span>&copy; {new Date().getFullYear()} SignalPilot Labs. All rights reserved.</span>
          </span>
          <div className="flex items-center gap-5">
            <a
              href="https://github.com"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 hover:text-[var(--color-text)] transition-colors"
            >
              <Github size={12} /> GitHub
            </a>
            <a href="#" className="hover:text-[var(--color-text)] transition-colors hover-underline">
              Docs
            </a>
            <a href="#" className="hover:text-[var(--color-text)] transition-colors hover-underline">
              Status
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
};
