// Bundle: ~4.3kb page JS (verified 2026-04-02)
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import AuthLayout from "@/components/AuthLayout";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState({ email: false, password: false });
  const [submitPath, setSubmitPath] = useState<"github" | "email" | null>(null);

  const isValidEmail = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email);
  const emailError = touched.email && !isValidEmail ? "INVALID EMAIL" : "";
  const passwordError = touched.password && password.length < 8 ? "MIN 8 CHARACTERS" : "";

  function handleGitHub() {
    // TODO: redirect to /api/auth/github — must be server-side OAuth flow, not client-side push
    setSubmitPath("github");
    if (process.env.NODE_ENV !== "production") console.log("[signup] github oauth initiated");
    router.push("/setup");
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setTouched({ email: true, password: true });
    if (!isValidEmail || password.length < 8) return;
    // TODO: wire to auth provider — POST to /api/auth/signup
    setSubmitPath("email");
    if (process.env.NODE_ENV !== "production") console.log("[signup] email/password submit", { email });
    router.push("/setup");
  }

  return (
    <AuthLayout>
        <h1 className="text-[clamp(28px,5vw,40px)] font-bold uppercase tracking-[0.05em] mb-16">
          CREATE ACCOUNT
        </h1>

        <button
          onClick={handleGitHub}
          disabled={submitPath !== null}
          className="w-full border-2 border-[var(--color-accent)] bg-transparent text-[var(--color-text)] font-bold text-sm uppercase tracking-[0.1em] py-4 px-6 cursor-pointer hover:bg-[var(--color-accent)] hover:text-[var(--color-bg)] disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitPath === "github" ? "REDIRECTING..." : "CONTINUE WITH GITHUB"}
        </button>

        <div className="flex items-center gap-4 my-12">
          <div className="flex-1 h-[2px] bg-[var(--color-dim)]" />
          <span className="text-[var(--color-dim)] text-xs tracking-[0.15em] uppercase">OR</span>
          <div className="flex-1 h-[2px] bg-[var(--color-dim)]" />
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-6">
          <div>
            <label htmlFor="signup-email" className="sr-only">Email</label>
            <input
              id="signup-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onBlur={() => setTouched((t) => ({ ...t, email: true }))}
              placeholder="EMAIL"
              autoComplete="email"
              disabled={submitPath !== null}
              aria-describedby={emailError ? "email-error" : undefined}
              className="w-full bg-transparent border-0 border-b-2 border-[var(--color-border)] text-[var(--color-text)] font-mono text-sm tracking-[0.1em] py-3 placeholder:text-[var(--color-dim)] placeholder:uppercase focus-visible:border-[var(--color-accent)] outline-none focus-visible:outline-2 focus-visible:outline-[var(--color-accent)] focus-visible:outline-offset-2"
            />
            {emailError && (
              <p id="email-error" role="alert" className="text-[var(--color-error)] text-xs tracking-[0.1em] mt-2">{emailError}</p>
            )}
          </div>

          <div>
            <label htmlFor="signup-password" className="sr-only">Password</label>
            <input
              id="signup-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onBlur={() => setTouched((t) => ({ ...t, password: true }))}
              placeholder="PASSWORD"
              autoComplete="new-password"
              disabled={submitPath !== null}
              aria-describedby={passwordError ? "password-error" : undefined}
              className="w-full bg-transparent border-0 border-b-2 border-[var(--color-border)] text-[var(--color-text)] font-mono text-sm tracking-[0.1em] py-3 placeholder:text-[var(--color-dim)] placeholder:uppercase focus-visible:border-[var(--color-accent)] outline-none focus-visible:outline-2 focus-visible:outline-[var(--color-accent)] focus-visible:outline-offset-2"
            />
            {passwordError && (
              <p id="password-error" role="alert" className="text-[var(--color-error)] text-xs tracking-[0.1em] mt-2">{passwordError}</p>
            )}
          </div>

          <button
            type="submit"
            disabled={submitPath !== null}
            className="w-full border-2 border-[var(--color-border)] bg-transparent text-[var(--color-text)] font-bold text-sm uppercase tracking-[0.1em] py-4 px-6 cursor-pointer hover:bg-[var(--color-text)] hover:text-[var(--color-bg)] disabled:opacity-50 disabled:cursor-not-allowed mt-4"
          >
            {submitPath === "email" ? "CREATING..." : "CREATE ACCOUNT"}
          </button>
        </form>

        <p className="text-[var(--color-dim)] text-xs tracking-[0.05em] mt-12 text-center">
          By signing up you agree to{" "}
          <a href="/terms" className="text-[var(--color-dim)] underline hover:text-[var(--color-accent)]">
            Terms
          </a>{" "}
          ·{" "}
          <a href="/privacy" className="text-[var(--color-dim)] underline hover:text-[var(--color-accent)]">
            Privacy
          </a>
        </p>

        {/* TODO: update href to /signin when that route exists */}
        <p className="text-[var(--color-dim)] text-xs tracking-[0.05em] mt-6 text-center">
          Already have an account?{" "}
          <a href="/signup" className="text-[var(--color-dim)] underline hover:text-[var(--color-accent)]">
            Sign in
          </a>
        </p>
    </AuthLayout>
  );
}
