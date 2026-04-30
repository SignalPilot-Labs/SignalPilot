"use client";

import { useState, useEffect } from "react";
import { useSignIn, useAuth, useClerk } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { AuthShell } from "@/components/auth/auth-shell";
import { Loader2 } from "lucide-react";

const INPUT_CLASS =
  "w-full px-3 py-2.5 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-[13px] text-[var(--color-text)] font-mono tracking-wide focus:outline-none focus:border-[var(--color-text-dim)] placeholder:text-[var(--color-text-dim)]/40";
const LABEL_CLASS =
  "block text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] mb-1.5";
const BTN_PRIMARY =
  "w-full px-4 py-2.5 bg-[var(--color-success)] text-[var(--color-bg)] text-[12px] font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30";
const BTN_SOCIAL =
  "flex items-center justify-center gap-2 w-full px-4 py-2.5 border border-[var(--color-border)] bg-[var(--color-bg-card)] hover:bg-[var(--color-bg-hover)] hover:border-[var(--color-border-hover)] text-[12px] text-[var(--color-text-muted)] tracking-wider transition-all font-mono";
const ERROR_CLASS = "text-[12px] text-[var(--color-error)] tracking-wider";
const LINK_CLASS =
  "text-[12px] text-[var(--color-text-dim)] tracking-wider hover:text-[var(--color-text)] transition-colors";

function GoogleIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18A10.96 10.96 0 0 0 1 12c0 1.77.42 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05" />
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
    </svg>
  );
}

export default function SignInPage() {
  const { isLoaded, signIn, setActive } = useSignIn();
  const { isSignedIn, orgId } = useAuth();
  const clerk = useClerk();
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<"email" | "password" | "code" | "totp">("email");
  const [redirecting, setRedirecting] = useState(false);

  // Detect 2FA requirement from signIn status or URL hash
  useEffect(() => {
    if (!isLoaded || !signIn) return;
    if (signIn.status === "needs_second_factor" || window.location.hash.includes("factor-two")) {
      setStep("totp");
    }
  }, [isLoaded, signIn?.status]);

  // Handle existing sessions — including "pending" sessions stuck on org selection
  useEffect(() => {
    if (!isLoaded) return;

    const sessions = clerk.client?.sessions ?? [];
    const pendingSession = sessions.find((s: { status: string }) => s.status === "pending");
    const activeSession = sessions.find((s: { status: string }) => s.status === "active");

    if (activeSession) {
      // Fully active session — redirect based on org
      setRedirecting(true);
      if (!orgId) {
        window.location.href = "/onboarding";
      } else {
        window.location.href = "/dashboard";
      }
      return;
    }

    if (pendingSession) {
      // Session exists but pending org selection — force-activate it and redirect to onboarding
      setRedirecting(true);
      setActive!({ session: pendingSession.id })
        .then(() => {
          window.location.href = "/onboarding";
        })
        .catch(() => {
          // If activation fails, sign out and let them start fresh
          clerk.signOut().then(() => {
            setRedirecting(false);
          });
        });
    }
  }, [isLoaded, isSignedIn, orgId, clerk, setActive]);

  if (!isLoaded || redirecting) {
    return (
      <AuthShell title="access terminal" subtitle="sign in to signalpilot">
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-4 h-4 animate-spin text-[var(--color-text-dim)]" />
        </div>
      </AuthShell>
    );
  }

  async function handleSocialSignIn(strategy: "oauth_google" | "oauth_github") {
    try {
      await signIn!.authenticateWithRedirect({
        strategy,
        redirectUrl: "/sign-in/sso-callback",
        redirectUrlComplete: "/dashboard",
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Social sign-in failed";
      setError(msg);
    }
  }

  async function handleEmailSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setError("");
    setLoading(true);

    try {
      const result = await signIn!.create({ identifier: email });

      // Check what verification strategies are available
      const firstFactor = result.supportedFirstFactors;
      const hasPassword = firstFactor?.some(
        (f: { strategy: string }) => f.strategy === "password"
      );
      const hasEmailCode = firstFactor?.some(
        (f: { strategy: string }) => f.strategy === "email_code"
      );

      if (hasPassword) {
        setStep("password");
      } else if (hasEmailCode) {
        // Send email code
        await signIn!.prepareFirstFactor({
          strategy: "email_code",
          emailAddressId: (firstFactor!.find(
            (f: { strategy: string }) => f.strategy === "email_code"
          ) as { emailAddressId: string }).emailAddressId,
        });
        setStep("code");
      } else {
        setError("No supported sign-in method for this account");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Sign-in failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  async function handlePasswordSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!password) return;
    setError("");
    setLoading(true);

    try {
      const result = await signIn!.attemptFirstFactor({
        strategy: "password",
        password,
      });

      if (result.status === "complete") {
        await setActive!({ session: result.createdSessionId });
        router.push("/dashboard");
      } else if (result.status === "needs_second_factor") {
        setStep("totp");
      } else {
        setError("Additional verification required");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Invalid password";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  async function handleCodeSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!code) return;
    setError("");
    setLoading(true);

    try {
      const result = await signIn!.attemptFirstFactor({
        strategy: "email_code",
        code,
      });

      if (result.status === "complete") {
        await setActive!({ session: result.createdSessionId });
        router.push("/dashboard");
      } else {
        setError("Verification failed");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Invalid code";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  async function handleTotpSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!totpCode) return;
    setError("");
    setLoading(true);

    try {
      const result = await signIn!.attemptSecondFactor({
        strategy: "totp",
        code: totpCode,
      });

      if (result.status === "complete") {
        await setActive!({ session: result.createdSessionId });
        window.location.href = "/dashboard";
      } else {
        setError("Verification failed");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Invalid code";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell title="access terminal" subtitle={step === "totp" ? "two-factor authentication" : "sign in to signalpilot"}>
      <div className="flex flex-col gap-4">
        {/* Social buttons */}
        {step === "email" && (
          <>
            <div className="flex flex-col gap-2">
              <button onClick={() => handleSocialSignIn("oauth_google")} className={BTN_SOCIAL}>
                <GoogleIcon /> continue with google
              </button>
              <button onClick={() => handleSocialSignIn("oauth_github")} className={BTN_SOCIAL}>
                <GitHubIcon /> continue with github
              </button>
            </div>

            <div className="flex items-center gap-3">
              <div className="flex-1 h-px bg-[var(--color-border)]" />
              <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider">or with email</span>
              <div className="flex-1 h-px bg-[var(--color-border)]" />
            </div>
          </>
        )}

        {/* Email step */}
        {step === "email" && (
          <form onSubmit={handleEmailSubmit} className="flex flex-col gap-4">
            <div>
              <label htmlFor="email" className={LABEL_CLASS}>email</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                autoFocus
                className={INPUT_CLASS}
              />
            </div>
            {error && <p className={ERROR_CLASS}>{error}</p>}
            <button type="submit" disabled={loading || !email.trim()} className={BTN_PRIMARY}>
              {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin mx-auto" /> : "continue"}
            </button>
            <a href="/sign-up" className={LINK_CLASS}>
              don&apos;t have an account? sign up
            </a>
          </form>
        )}

        {/* Password step */}
        {step === "password" && (
          <form onSubmit={handlePasswordSubmit} className="flex flex-col gap-4">
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
              signing in as <code className="text-[var(--color-text-muted)]">{email}</code>
            </p>
            <div>
              <label htmlFor="password" className={LABEL_CLASS}>password</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoFocus
                className={INPUT_CLASS}
              />
            </div>
            {error && <p className={ERROR_CLASS}>{error}</p>}
            <button type="submit" disabled={loading || !password} className={BTN_PRIMARY}>
              {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin mx-auto" /> : "sign in"}
            </button>
            <button type="button" onClick={() => { setStep("email"); setError(""); setPassword(""); }} className={LINK_CLASS}>
              ← use a different email
            </button>
          </form>
        )}

        {/* Code step */}
        {step === "code" && (
          <form onSubmit={handleCodeSubmit} className="flex flex-col gap-4">
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
              we sent a code to <code className="text-[var(--color-text-muted)]">{email}</code>
            </p>
            <div>
              <label htmlFor="code" className={LABEL_CLASS}>verification code</label>
              <input
                id="code"
                type="text"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="123456"
                autoFocus
                autoComplete="one-time-code"
                className={INPUT_CLASS}
              />
            </div>
            {error && <p className={ERROR_CLASS}>{error}</p>}
            <button type="submit" disabled={loading || !code} className={BTN_PRIMARY}>
              {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin mx-auto" /> : "verify"}
            </button>
            <button type="button" onClick={() => { setStep("email"); setError(""); setCode(""); }} className={LINK_CLASS}>
              ← use a different email
            </button>
          </form>
        )}

        {/* TOTP 2FA step */}
        {step === "totp" && (
          <form onSubmit={handleTotpSubmit} className="flex flex-col gap-4">
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
              enter the 6-digit code from your authenticator app
            </p>
            <div>
              <label htmlFor="totp" className={LABEL_CLASS}>verification code</label>
              <input
                id="totp"
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ""))}
                placeholder="000000"
                autoFocus
                autoComplete="one-time-code"
                className={INPUT_CLASS}
              />
            </div>
            {error && <p className={ERROR_CLASS}>{error}</p>}
            <button type="submit" disabled={loading || totpCode.length !== 6} className={BTN_PRIMARY}>
              {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin mx-auto" /> : "verify"}
            </button>
          </form>
        )}
      </div>
    </AuthShell>
  );
}
