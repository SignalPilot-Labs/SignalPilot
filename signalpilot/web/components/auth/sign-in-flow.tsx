"use client";

/**
 * Sign-in flow using @clerk/elements.
 * Isolated in this file so it can be dynamically imported with ssr:false
 * from the sign-in page — @clerk/elements uses browser-only `location` API
 * at module scope which fails during Next.js SSR build.
 */

import * as SignIn from "@clerk/elements/sign-in";
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

export function SignInFlow() {
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
            <FieldRow name="identifier" type="email" label="email" />
            <FieldRow name="password" type="password" label="password" />
            <GlobalErrorBanner />
            <PrimaryAction submit>continue</PrimaryAction>
            <div className="flex flex-col items-center gap-2">
              <SecondaryAction navigate="forgot-password">
                forgot password?
              </SecondaryAction>
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
          <div className="flex flex-col gap-4">
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

            {/* totp / backup_code / phone_code — round 4 */}
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
            <SignIn.SupportedStrategy name="reset_password_email_code" asChild>
              <button className="px-5 py-2.5 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] uppercase tracking-wider hover:opacity-90 transition-opacity disabled:opacity-40 font-mono w-full focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-card)]">
                email me a reset code
              </button>
            </SignIn.SupportedStrategy>
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
