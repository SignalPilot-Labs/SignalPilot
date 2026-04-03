// Bundle: ~4.3kb page JS (verified 2026-04-02)
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import AuthLayout from "@/components/AuthLayout";
import OAuthButtons from "@/components/OAuthButtons";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState({ email: false, password: false });
  const [submitPath, setSubmitPath] = useState<"github" | "google" | "email" | null>(null);
  const [apiError, setApiError] = useState<string>("");

  const isValidEmail = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email);
  const emailError = touched.email && !isValidEmail ? "INVALID EMAIL" : "";
  const passwordError = touched.password && password.length < 8 ? "MIN 8 CHARACTERS" : "";

  function handleGitHub() {
    setSubmitPath("github");
    if (process.env.NODE_ENV !== "production") console.log("[signup] github oauth initiated");
    signIn("github", { callbackUrl: "/setup" });
  }

  function handleGoogle() {
    setSubmitPath("google");
    if (process.env.NODE_ENV !== "production") console.log("[signup] google oauth initiated");
    signIn("google", { callbackUrl: "/setup" });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setTouched({ email: true, password: true });
    if (!isValidEmail || password.length < 8) return;
    setSubmitPath("email");
    setApiError("");
    if (process.env.NODE_ENV !== "production") console.log("[signup] email/password submit", { email });

    try {
      const res = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setApiError(data.error ?? "SIGNUP_FAILED");
        setSubmitPath(null);
        return;
      }

      const result = await signIn("credentials", {
        email,
        password,
        redirect: false,
      });

      if (result?.error) {
        setApiError(result.error);
        setSubmitPath(null);
        return;
      }

      router.push("/setup");
    } catch {
      setApiError("NETWORK_ERROR");
      setSubmitPath(null);
    }
  }

  return (
    <AuthLayout>
        <h1 className="text-[clamp(28px,5vw,40px)] font-bold uppercase tracking-[0.05em] mb-16">
          CREATE ACCOUNT
        </h1>

        <OAuthButtons
          onGitHub={handleGitHub}
          onGoogle={handleGoogle}
          disabled={submitPath !== null}
          githubLabel={submitPath === "github" ? "REDIRECTING..." : undefined}
          googleLabel={submitPath === "google" ? "REDIRECTING..." : undefined}
        />

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

          {apiError && (
            <p id="api-error" role="alert" className="text-[var(--color-error)] text-xs tracking-[0.1em]">{apiError}</p>
          )}

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

        <p className="text-[var(--color-dim)] text-xs tracking-[0.05em] mt-6 text-center">
          Already have an account?{" "}
          <a href="/signin" className="text-[var(--color-dim)] underline hover:text-[var(--color-accent)]">
            Sign in
          </a>
        </p>
    </AuthLayout>
  );
}
