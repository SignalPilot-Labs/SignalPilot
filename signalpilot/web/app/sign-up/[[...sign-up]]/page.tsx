"use client";

import { useState, useEffect } from "react";
import { useSignUp } from "@clerk/nextjs";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthShell } from "@/components/auth/auth-shell";
import { Loader2 } from "lucide-react";

const INPUT_CLASS =
  "w-full px-3 py-2.5 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-[13px] text-[var(--color-text)] font-mono tracking-wide focus:outline-none focus:border-[var(--color-text-dim)] placeholder:text-[var(--color-text-dim)]/40";
const LABEL_CLASS =
  "block text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] mb-1.5";
const BTN_PRIMARY =
  "w-full px-4 py-2.5 bg-[var(--color-success)] text-[var(--color-bg)] text-[12px] font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30";
const ERROR_CLASS = "text-[12px] text-[var(--color-error)] tracking-wider";
const LINK_CLASS =
  "text-[12px] text-[var(--color-text-dim)] tracking-wider hover:text-[var(--color-text)] transition-colors";

export default function SignUpPage() {
  const { isLoaded, signUp, setActive } = useSignUp();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<"form" | "verify">("form");

  // Handle invitation ticket from Clerk invite emails
  const ticket = searchParams.get("__clerk_ticket");
  useEffect(() => {
    if (!isLoaded || !signUp || !ticket) return;
    setLoading(true);
    signUp.create({ strategy: "ticket", ticket })
      .then(async (result) => {
        if (result.status === "complete") {
          await setActive!({ session: result.createdSessionId });
          router.push("/dashboard");
        } else {
          // Needs more steps (e.g. password, verification)
          setStep("form");
          setLoading(false);
        }
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Invitation link failed");
        setLoading(false);
      });
  }, [isLoaded, signUp, ticket, setActive, router]);

  if (!isLoaded || (ticket && loading)) {
    return (
      <AuthShell title="boot sequence" subtitle={ticket ? "accepting invitation..." : "create your signalpilot account"}>
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-4 h-4 animate-spin text-[var(--color-text-dim)]" />
        </div>
        {error && <p className={ERROR_CLASS}>{error}</p>}
      </AuthShell>
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) return;
    setError("");
    setLoading(true);

    try {
      await signUp!.create({
        emailAddress: email,
        password,
      });

      // Send email verification code
      await signUp!.prepareEmailAddressVerification({
        strategy: "email_code",
      });

      setStep("verify");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Sign-up failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  async function handleVerify(e: React.FormEvent) {
    e.preventDefault();
    if (!code) return;
    setError("");
    setLoading(true);

    try {
      const result = await signUp!.attemptEmailAddressVerification({
        code,
      });

      if (result.status === "complete") {
        await setActive!({ session: result.createdSessionId });
        router.push("/onboarding");
      } else {
        setError("Verification incomplete — please try again");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Invalid code";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell title="boot sequence" subtitle="create your signalpilot account">
      <div className="flex flex-col gap-4">
        {step === "form" && (
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
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
            <div>
              <label htmlFor="password" className={LABEL_CLASS}>password</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className={INPUT_CLASS}
              />
            </div>
            {error && <p className={ERROR_CLASS}>{error}</p>}
            <button type="submit" disabled={loading || !email.trim() || !password} className={BTN_PRIMARY}>
              {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin mx-auto" /> : "create account"}
            </button>
            <a href="/sign-in" className={LINK_CLASS}>
              already have an account? sign in
            </a>
          </form>
        )}

        {step === "verify" && (
          <form onSubmit={handleVerify} className="flex flex-col gap-4">
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider">
              we sent a verification code to <code className="text-[var(--color-text-muted)]">{email}</code>
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
              {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin mx-auto" /> : "verify email"}
            </button>
            <button type="button" onClick={() => { setStep("form"); setError(""); setCode(""); }} className={LINK_CLASS}>
              ← back
            </button>
          </form>
        )}
      </div>
    </AuthShell>
  );
}
