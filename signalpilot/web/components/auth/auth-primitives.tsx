/**
 * Small styled wrappers around Clerk Elements primitives.
 * Terminal aesthetic: monospace, 0 radius, CSS variable colors.
 * Target: < 150 lines (icons split into social-icons.tsx).
 *
 * Note: @clerk/elements inherits `FormSubmitProps` from @radix-ui/react-form
 * whose `children` type is a render-function `(validity) => ReactNode`.
 * Clerk's own docs show string children working fine; the type mismatch is a
 * Clerk/Radix upstream bug. We cast via `as unknown` to unblock typecheck.
 */

import * as Clerk from "@clerk/elements/common";
import * as SignIn from "@clerk/elements/sign-in";
import * as SignUp from "@clerk/elements/sign-up";
import React from "react";
import type { ReactNode } from "react";
import { GoogleIcon, GitHubIcon } from "./social-icons";

// Clerk Action children type requires a render fn but docs show string children working.
// The discriminated union prop types are also very strict (each variant has `never` for other
// action types). We cast to `any` on the Action component to bypass both upstream Clerk type
// mismatches — this is a known issue with @clerk/elements@^0.24.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const SignInActionAny = SignIn.Action as React.ComponentType<any>;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const SignUpActionAny = SignUp.Action as React.ComponentType<any>;


// ---------------------------------------------------------------------------
// Field row — label + input + error
// ---------------------------------------------------------------------------

export interface FieldRowProps {
  name: string;
  type?: string;
  label: string;
  /** Optional ref forwarded to the underlying Clerk.Input render slot */
  inputRef?: React.RefObject<HTMLInputElement | null>;
}

export function FieldRow({ name, type = "text", label, inputRef }: FieldRowProps) {
  return (
    <Clerk.Field name={name} className="flex flex-col gap-1">
      <Clerk.Label className="text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)]">
        {label}
      </Clerk.Label>
      <Clerk.Input
        type={type}
        ref={inputRef}
        className="px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-[13px] text-[var(--color-text)] font-mono tracking-wide focus:outline-none focus:border-[var(--color-border-hover)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:border-[var(--color-text)] w-full"
      />
      <Clerk.FieldError className="text-[11px] text-[var(--color-error)] tracking-wider" />
    </Clerk.Field>
  );
}

// ---------------------------------------------------------------------------
// OTP input — 6-box terminal style
// ---------------------------------------------------------------------------

export function OtpInput({ name }: { name: string }) {
  return (
    <Clerk.Field name={name} className="flex flex-col gap-1">
      <Clerk.Input
        type="otp"
        className="flex gap-2 [&>input]:w-10 [&>input]:h-10 [&>input]:text-center [&>input]:bg-[var(--color-bg-input)] [&>input]:border [&>input]:border-[var(--color-border)] [&>input]:text-[var(--color-text)] [&>input]:font-mono [&>input]:text-lg [&>input]:focus:outline-none [&>input]:focus:border-[var(--color-border-hover)] [&>input]:focus-visible:outline-none [&>input]:focus-visible:ring-1 [&>input]:focus-visible:ring-[var(--color-text)] [&>input]:focus-visible:border-[var(--color-text)]"
      />
      <Clerk.FieldError className="text-[11px] text-[var(--color-error)] tracking-wider" />
    </Clerk.Field>
  );
}

// ---------------------------------------------------------------------------
// Action buttons
// ---------------------------------------------------------------------------

export const FIELD_INPUT_CLASS =
  "px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-[13px] text-[var(--color-text)] font-mono tracking-wide focus:outline-none focus:border-[var(--color-border-hover)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:border-[var(--color-text)] w-full";
export const PRIMARY_BTN_CLASS =
  "px-5 py-2.5 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] uppercase tracking-wider hover:opacity-90 transition-opacity disabled:opacity-40 font-mono w-full focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-card)]";
// Shared typography class constants — used across security sections.
// Defined once here to prevent drift across files.
export const LABEL_CLASS =
  "text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)]";
export const ERROR_CLASS =
  "text-[11px] text-[var(--color-error)] tracking-wider";
export const NEUTRAL_CLASS =
  "text-[11px] text-[var(--color-text-dim)] tracking-wider";
export const SECONDARY_BTN_CLASS =
  "text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider underline underline-offset-2 transition-colors font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]";
export const DANGER_BTN_CLASS =
  "px-5 py-2.5 bg-[var(--color-error)]/10 border border-[var(--color-error)]/40 text-[var(--color-error)] text-[12px] uppercase tracking-wider hover:bg-[var(--color-error)]/20 transition-colors disabled:opacity-40 font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-card)]";

export function PrimaryAction({
  children,
  submit,
  navigate,
  resend,
}: {
  children: ReactNode;
  submit?: boolean;
  navigate?: string;
  resend?: boolean;
}) {
  if (navigate) {
    return <SignInActionAny navigate={navigate} className={PRIMARY_BTN_CLASS}>{children}</SignInActionAny>;
  }
  if (resend) {
    return <SignInActionAny resend className={PRIMARY_BTN_CLASS}>{children}</SignInActionAny>;
  }
  return <SignInActionAny submit className={PRIMARY_BTN_CLASS}>{children}</SignInActionAny>;
}

export function SignUpPrimaryAction({
  children,
  submit,
  resend,
}: {
  children: ReactNode;
  submit?: boolean;
  resend?: boolean;
}) {
  if (resend) {
    return <SignUpActionAny resend className={PRIMARY_BTN_CLASS}>{children}</SignUpActionAny>;
  }
  return <SignUpActionAny submit className={PRIMARY_BTN_CLASS}>{children}</SignUpActionAny>;
}

export function SecondaryAction({
  children,
  navigate,
  resend,
}: {
  children: ReactNode;
  navigate?: string;
  resend?: boolean;
}) {
  if (navigate) {
    return <SignInActionAny navigate={navigate} className={SECONDARY_BTN_CLASS}>{children}</SignInActionAny>;
  }
  if (resend) {
    return <SignInActionAny resend className={SECONDARY_BTN_CLASS}>{children}</SignInActionAny>;
  }
  return <SignInActionAny submit className={SECONDARY_BTN_CLASS}>{children}</SignInActionAny>;
}

export function SignUpSecondaryAction({
  children,
  resend,
}: {
  children: ReactNode;
  resend?: boolean;
}) {
  if (resend) {
    return <SignUpActionAny resend className={SECONDARY_BTN_CLASS}>{children}</SignUpActionAny>;
  }
  return <SignUpActionAny submit className={SECONDARY_BTN_CLASS}>{children}</SignUpActionAny>;
}

// ---------------------------------------------------------------------------
// Social connection button
// ---------------------------------------------------------------------------

export function SocialButton({ name }: { name: "google" | "github" }) {
  return (
    <Clerk.Connection
      name={name}
      className="flex items-center justify-center gap-2 w-full px-4 py-2.5 border border-[var(--color-border)] bg-[var(--color-bg-card)] hover:bg-[var(--color-bg-hover)] hover:border-[var(--color-border-hover)] text-[12px] text-[var(--color-text-muted)] tracking-wider transition-all font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:border-[var(--color-text)]"
    >
      {name === "google" ? <GoogleIcon /> : <GitHubIcon />}
      continue with {name}
    </Clerk.Connection>
  );
}

// ---------------------------------------------------------------------------
// Divider
// ---------------------------------------------------------------------------

export function Divider({ label = "or" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 my-1">
      <div className="flex-1 h-px bg-[var(--color-border)]" />
      <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider font-mono whitespace-nowrap">
        {label}
      </span>
      <div className="flex-1 h-px bg-[var(--color-border)]" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Global error banner
// ---------------------------------------------------------------------------

export function GlobalErrorBanner() {
  return (
    <Clerk.GlobalError className="px-3 py-2 bg-[var(--color-error)]/10 border border-[var(--color-error)]/30 text-[12px] text-[var(--color-error)] tracking-wider font-mono" />
  );
}

// ---------------------------------------------------------------------------
// Footer link (cross-flow nav)
// ---------------------------------------------------------------------------

export function FooterLink({
  children,
  navigate,
}: {
  children: ReactNode;
  navigate: "sign-in" | "sign-up";
}) {
  return (
    <Clerk.Link
      navigate={navigate}
      className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider transition-colors font-mono text-center focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]"
    >
      {children}
    </Clerk.Link>
  );
}
