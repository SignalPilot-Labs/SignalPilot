"use client";

/**
 * Sign-up flow using @clerk/elements.
 * Isolated in this file so it can be dynamically imported with ssr:false
 * from the sign-up page — @clerk/elements uses browser-only `location` API
 * at module scope which fails during Next.js SSR build.
 */

import * as SignUp from "@clerk/elements/sign-up";
import { StepTransition } from "./step-transition";
import {
  FieldRow,
  OtpInput,
  SignUpPrimaryAction,
  SignUpSecondaryAction,
  SocialButton,
  Divider,
  GlobalErrorBanner,
  FooterLink,
} from "./auth-primitives";

export function SignUpFlow() {
  return (
    <SignUp.Root routing="virtual">
      {/* ── Step: start ── */}
      <SignUp.Step name="start">
        <StepTransition stepKey="start">
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <SocialButton name="google" />
              <SocialButton name="github" />
            </div>
            <Divider label="or with email" />
            <FieldRow name="emailAddress" type="email" label="email" />
            <FieldRow name="password" type="password" label="password" />
            <GlobalErrorBanner />
            <SignUp.Captcha />
            <SignUpPrimaryAction submit>create account</SignUpPrimaryAction>
            <FooterLink navigate="sign-in">
              already have an account? sign in
            </FooterLink>
          </div>
        </StepTransition>
      </SignUp.Step>

      {/* ── Step: continue (extra fields if required by Clerk) ── */}
      <SignUp.Step name="continue">
        <StepTransition stepKey="continue">
          <div className="flex flex-col gap-4">
            <FieldRow name="username" type="text" label="username" />
            <GlobalErrorBanner />
            <SignUpPrimaryAction submit>continue</SignUpPrimaryAction>
          </div>
        </StepTransition>
      </SignUp.Step>

      {/* ── Step: verifications ── */}
      <SignUp.Step name="verifications">
        <StepTransition stepKey="verifications">
          <div className="flex flex-col gap-4">
            <SignUp.Strategy name="email_code">
              <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider font-mono">
                enter the code we sent to your email
              </p>
              <OtpInput name="code" />
              <GlobalErrorBanner />
              <SignUpPrimaryAction submit>verify email</SignUpPrimaryAction>
              <SignUpSecondaryAction resend>resend code</SignUpSecondaryAction>
            </SignUp.Strategy>
          </div>
        </StepTransition>
      </SignUp.Step>
    </SignUp.Root>
  );
}
