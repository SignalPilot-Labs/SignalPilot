"use client";

/**
 * TeamSwitcher — sidebar component showing the active team + sign-out.
 * Minimum viable variant: active team name + user email + sign-out button.
 *
 * MUST be dynamically imported with ssr:false and gated on clerkEnabled.
 * useOrganization / useOrganizationList will throw if Organizations are
 * disabled on the Clerk instance — wrapped in an ErrorBoundary in sidebar.tsx.
 *
 * Terminal aesthetic: 0 radius, CSS variable colors, monospace font.
 */

import { useRef, useState, useEffect, useCallback } from "react";
import { useClerk, useUser, useOrganization } from "@clerk/nextjs";
import { Component, type ReactNode } from "react";
import { LogOut, ChevronDown } from "lucide-react";

// ---------------------------------------------------------------------------
// Inline error boundary — catches "Organizations not enabled" throws
// ---------------------------------------------------------------------------

interface InlineErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class InlineErrorBoundary extends Component<
  { children: ReactNode },
  InlineErrorBoundaryState
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): InlineErrorBoundaryState {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="px-3 py-2 border-t border-[var(--color-border)]">
          <p className="text-[10px] text-[var(--color-error)] tracking-wider font-mono truncate" title={this.state.error?.message}>
            team switcher error: {this.state.error?.message ?? "unknown"}
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

// ---------------------------------------------------------------------------
// TeamSwitcherInner — calls Clerk hooks
// ---------------------------------------------------------------------------

function TeamSwitcherInner({ displayName }: { displayName: string }) {
  const { signOut } = useClerk();
  const { user } = useUser();
  const { organization } = useOrganization();
  const [open, setOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const teamName = organization?.name ?? "no team";
  const email = user?.primaryEmailAddress?.emailAddress ?? displayName;

  // Close on outside click or Escape
  const handleOutside = useCallback((e: MouseEvent) => {
    if (
      popoverRef.current &&
      !popoverRef.current.contains(e.target as Node) &&
      buttonRef.current &&
      !buttonRef.current.contains(e.target as Node)
    ) {
      setOpen(false);
    }
  }, []);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        // Restore focus to the trigger so keyboard users aren't stranded
        buttonRef.current?.focus();
      }
    },
    [],
  );

  useEffect(() => {
    if (open) {
      document.addEventListener("mousedown", handleOutside);
      document.addEventListener("keydown", handleKeyDown);
      // Auto-focus first focusable element in the popover
      const raf = requestAnimationFrame(() => {
        const first = popoverRef.current?.querySelector<HTMLElement>(
          "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])",
        );
        first?.focus();
      });
      return () => {
        cancelAnimationFrame(raf);
        document.removeEventListener("mousedown", handleOutside);
        document.removeEventListener("keydown", handleKeyDown);
      };
    } else {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, handleOutside, handleKeyDown]);

  async function handleSignOut() {
    setOpen(false);
    await signOut();
  }

  return (
    <div className="relative px-3 py-2 border-t border-[var(--color-border)]">
      {/* Trigger button */}
      <button
        ref={buttonRef}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="true"
        aria-expanded={open}
        className="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-[var(--color-bg-hover)] transition-colors text-left focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]"
      >
        {/* Team avatar — first letter of team name, or dash for no-team state */}
        <span
          className="flex-shrink-0 w-5 h-5 flex items-center justify-center bg-[var(--color-border)] text-[10px] font-mono text-[var(--color-text-muted)] uppercase"
          aria-hidden="true"
        >
          {organization ? teamName.charAt(0) : "–"}
        </span>
        <span className="flex-1 text-[11px] text-[var(--color-text-dim)] tracking-wide truncate font-mono">
          {teamName}
        </span>
        <ChevronDown
          size={10}
          className={`flex-shrink-0 text-[var(--color-text-dim)] transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {/* Popover */}
      {open && (
        <div
          ref={popoverRef}
          role="dialog"
          aria-label="Team menu"
          className="absolute bottom-full left-3 right-3 mb-1 bg-[var(--color-bg-card)] border border-[var(--color-border)] shadow-lg z-50 animate-scale-in"
        >
          {/* Current team + user info */}
          <div className="px-3 py-2.5 border-b border-[var(--color-border)]">
            <p className="text-[11px] text-[var(--color-text)] tracking-wider font-mono truncate" title={teamName}>
              {teamName}
            </p>
            <p className="text-[10px] text-[var(--color-text-dim)] tracking-wider font-mono truncate mt-0.5" title={email}>
              {email}
            </p>
          </div>

          {/* Sign out */}
          <button
            onClick={handleSignOut}
            className="w-full flex items-center gap-2 px-3 py-2 text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] tracking-wider font-mono transition-colors focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-inset"
          >
            <LogOut size={10} className="flex-shrink-0" />
            sign out
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TeamSwitcher — exported default with error boundary wrapper
// ---------------------------------------------------------------------------

export default function TeamSwitcher({ displayName }: { displayName: string }) {
  return (
    <InlineErrorBoundary>
      <TeamSwitcherInner displayName={displayName} />
    </InlineErrorBoundary>
  );
}
