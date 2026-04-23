"use client";

/**
 * Sign-in flow using @clerk/elements.
 * Isolated in this file so it can be dynamically imported with ssr:false
 * from the sign-in page — @clerk/elements uses browser-only `location` API
 * at module scope which fails during Next.js SSR build.
 */

import * as SignIn from "@clerk/elements/sign-in";
import React, { useRef, useState } from "react";
import { StepTransition } from "./step-transition";
import {
  FieldRow,
  OtpInput,
  PrimaryAction,
  SecondaryAction,
  SocialButton,
  Divider,
  GlobalErrorBanner,
  FooterLink,
} from "./auth-primitives";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const SupportedStrategyAny = SignIn.SupportedStrategy as React.ComponentType<any>;

export function SignInFlow() {
  const identifierRef = useRef<HTMLInputElement | null>(null);
  const [forgotPasswordError, setForgotPasswordError] = useState<string | null>(null);

  return (
    <SignIn.Root routing="virtual">
      {/* ── Step: start ── */}
      <SignIn.Step name="start">
        <StepTransition stepKey="start">
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <SocialButton name="google" />
              <SocialButton name="github" />
            </div>
            <Divider label="or with email" />
            {/* Wire onChange via render slot to track identifier value */}
            <FieldRow
              name="identifier"
              type="email"
              label="email"
              inputRef={identifierRef}
            />
            <FieldRow name="password" type="password" label="password" />
            <GlobalErrorBanner />
            <PrimaryAction submit>continue</PrimaryAction>
            <div className="flex flex-col items-center gap-2">
              {forgotPasswordError && (
                <p className="text-[11px] text-[var(--color-error)] tracking-wider">
                  {forgotPasswordError}
                </p>
              )}
              {/* Approach (a): guard navigate="forgot-password" at click time */}
              <SignIn.Action
                navigate="forgot-password"
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                {...({} as any)}
                asChild
              >
                <button
                  className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider underline underline-offset-2 transition-colors font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]"
                  onClick={(e: React.MouseEvent<HTMLButtonElement>) => {
                    const val = identifierRef.current?.value ?? "";
                    if (!val.trim()) {
                      e.preventDefault();
                      setForgotPasswordError("enter your email first");
                    } else {
                      setForgotPasswordError(null);
                    }
                  }}
                >
                  forgot password?
                </button>
              </SignIn.Action>
              <FooterLink navigate="sign-up">
                no account? create one
              </FooterLink>
            </div>
          </div>
        </StepTransition>
      </SignIn.Step>

      {/* ── Step: verifications ── */}
      <SignIn.Step name="verifications">
        <StepTransition stepKey="verifications">
          {/* aria-live announces MFA strategy switches to screen readers */}
          <div className="flex flex-col gap-4" aria-live="polite" aria-atomic="false">
            <SignIn.Strategy name="password">
              <FieldRow name="password" type="password" label="password" />
              <GlobalErrorBanner />
              <PrimaryAction submit>sign in</PrimaryAction>
            </SignIn.Strategy>

            <SignIn.Strategy name="email_code">
              <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider font-mono">
                code sent to{" "}
                <span className="text-[var(--color-text-muted)]">
                  <SignIn.SafeIdentifier />
                </span>
              </p>
              <OtpInput name="code" />
              <GlobalErrorBanner />
              <PrimaryAction submit>verify</PrimaryAction>
              <SecondaryAction resend>resend code</SecondaryAction>
            </SignIn.Strategy>

            {/* ── MFA strategies ── */}
            <SignIn.Strategy name="totp">
              <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider font-mono">
                code from your authenticator app
              </p>
              <OtpInput name="code" />
              <GlobalErrorBanner />
              <PrimaryAction submit>verify</PrimaryAction>
            </SignIn.Strategy>

            <SignIn.Strategy name="backup_code">
              <FieldRow name="code" type="text" label="backup code" />
              <GlobalErrorBanner />
              <PrimaryAction submit>verify</PrimaryAction>
            </SignIn.Strategy>

            <SignIn.Strategy name="phone_code">
              <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider font-mono">
                code sent to{" "}
                <span className="text-[var(--color-text-muted)]">
                  <SignIn.SafeIdentifier />
                </span>
              </p>
              <OtpInput name="code" />
              <GlobalErrorBanner />
              <PrimaryAction submit>verify</PrimaryAction>
              <SecondaryAction resend>resend code</SecondaryAction>
            </SignIn.Strategy>

            {/* Strategy switcher — Clerk renders only supported strategies.
                aria-live announces when the active strategy changes.
                The switcher block is always mounted; Clerk suppresses individual
                SupportedStrategy buttons when that factor isn't enrolled, so the
                header div may be empty — CSS :has() cannot hide it in all browsers,
                so we rely on Clerk's own suppression for cleanliness. */}
            <div
              aria-live="polite"
              aria-label="alternative sign-in methods"
              className="flex flex-col items-center gap-1 pt-1 border-t border-[var(--color-border)]"
            >
              <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider mb-1">
                use a different method
              </p>
              <SupportedStrategyAny
                name="totp"
                className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider underline underline-offset-2 transition-colors font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]"
              >
                authenticator app
              </SupportedStrategyAny>
              <SupportedStrategyAny
                name="backup_code"
                className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider underline underline-offset-2 transition-colors font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]"
              >
                backup code
              </SupportedStrategyAny>
              <SupportedStrategyAny
                name="phone_code"
                className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider underline underline-offset-2 transition-colors font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]"
              >
                sms code
              </SupportedStrategyAny>
            </div>
          </div>
        </StepTransition>
      </SignIn.Step>

      {/* ── Step: forgot-password ── */}
      <SignIn.Step name="forgot-password">
        <StepTransition stepKey="forgot-password">
          <div className="flex flex-col gap-4">
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider font-mono">
              enter your email address and we&apos;ll send a reset code.
            </p>
            <GlobalErrorBanner />
            {/* SupportedStrategy doesn't accept className — use asChild */}
            <SupportedStrategyAny name="reset_password_email_code" asChild>
              <button className="px-5 py-2.5 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] uppercase tracking-wider hover:opacity-90 transition-opacity disabled:opacity-40 font-mono w-full focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-card)]">
                email me a reset code
              </button>
            </SupportedStrategyAny>
            <FooterLink navigate="sign-in">← back to sign in</FooterLink>
          </div>
        </StepTransition>
      </SignIn.Step>

      {/* ── Step: reset-password ── */}
      <SignIn.Step name="reset-password">
        <StepTransition stepKey="reset-password">
          <div className="flex flex-col gap-4">
            <FieldRow name="password" type="password" label="new password" />
            <FieldRow
              name="confirmPassword"
              type="password"
              label="confirm password"
            />
            <GlobalErrorBanner />
            <PrimaryAction submit>set new password</PrimaryAction>
          </div>
        </StepTransition>
      </SignIn.Step>
    </SignIn.Root>
  );
}
