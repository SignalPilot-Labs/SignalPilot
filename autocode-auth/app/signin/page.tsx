"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import AuthLayout from "@/components/AuthLayout";
import OAuthButtons from "@/components/OAuthButtons";

export default function SigninPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState({ email: false, password: false });
  const [submitPath, setSubmitPath] = useState<"github" | "google" | "email" | null>(null);
  const [credentialsError, setCredentialsError] = useState("");

  const isValidEmail = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email);
  const emailError = touched.email && !isValidEmail ? "INVALID EMAIL" : "";
  const passwordError = touched.password && password.length === 0 ? "REQUIRED" : "";

  function handleGitHub() {
    setSubmitPath("github");
    signIn("github", { callbackUrl: "/setup" });
  }

  function handleGoogle() {
    setSubmitPath("google");
    signIn("google", { callbackUrl: "/setup" });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setTouched({ email: true, password: true });
    if (!isValidEmail || password.length === 0) return;
    setCredentialsError("");
    setSubmitPath("email");
    const result = await signIn("credentials", { email, password, redirect: false });
    if (result?.error) {
      setCredentialsError("INVALID CREDENTIALS");
      setSubmitPath(null);
      return;
    }
    router.push("/setup");
  }

  return (
    <AuthLayout>
      <h1 className="text-[clamp(28px,5vw,40px)] font-bold uppercase tracking-[0.05em] mb-16">
        SIGN IN
      </h1>

      <OAuthButtons
        onGitHub={handleGitHub}
        onGoogle={handleGoogle}
        disabled={submitPath !== null}
        githubLabel={submitPath === "github" ? "REDIRECTING..." : undefined}
        googleLabel={submitPath === "google" ? "REDIRECTING..." : undefined}
      />

      {credentialsError && (
        <p
          id="credentials-error"
          role="alert"
          className="text-[var(--color-error)] text-xs tracking-[0.1em] mb-6"
        >
          {credentialsError}
        </p>
      )}

      <form onSubmit={handleSubmit} className="flex flex-col gap-6">
        <div>
          <label htmlFor="signin-email" className="sr-only">Email</label>
          <input
            id="signin-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onBlur={() => setTouched((t) => ({ ...t, email: true }))}
            placeholder="EMAIL"
            autoComplete="email"
            disabled={submitPath !== null}
            aria-describedby={emailError ? "email-error" : credentialsError ? "credentials-error" : undefined}
            className="w-full bg-transparent border-0 border-b-2 border-[var(--color-border)] text-[var(--color-text)] font-mono text-sm tracking-[0.1em] py-3 placeholder:text-[var(--color-dim)] placeholder:uppercase focus-visible:border-[var(--color-accent)] outline-none focus-visible:outline-2 focus-visible:outline-[var(--color-accent)] focus-visible:outline-offset-2"
          />
          {emailError && (
            <p id="email-error" role="alert" className="text-[var(--color-error)] text-xs tracking-[0.1em] mt-2">{emailError}</p>
          )}
        </div>

        <div>
          <label htmlFor="signin-password" className="sr-only">Password</label>
          <input
            id="signin-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onBlur={() => setTouched((t) => ({ ...t, password: true }))}
            placeholder="PASSWORD"
            autoComplete="current-password"
            disabled={submitPath !== null}
            aria-describedby={passwordError ? "password-error" : credentialsError ? "credentials-error" : undefined}
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
          {submitPath === "email" ? "SIGNING IN..." : "SIGN IN"}
        </button>
      </form>

      <p className="text-[var(--color-dim)] text-xs tracking-[0.05em] mt-12 text-center">
        Don&apos;t have an account?{" "}
        <a href="/signup" className="text-[var(--color-dim)] underline hover:text-[var(--color-accent)]">
          Sign up
        </a>
      </p>
    </AuthLayout>
  );
}
