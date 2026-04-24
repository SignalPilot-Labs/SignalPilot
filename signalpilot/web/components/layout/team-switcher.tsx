"use client";

/**
 * TeamSwitcher — sidebar component showing the active team + sign-out.
 * Supports switching between orgs, creating a new org, and filtering when
 * membership count exceeds 10. Threshold-gated search, inline create form.
 *
 * MUST be dynamically imported with ssr:false and gated on clerkEnabled.
 * useOrganization / useOrganizationList will throw if Organizations are
 * disabled on the Clerk instance — wrapped in an ErrorBoundary in sidebar.tsx.
 *
 * Terminal aesthetic: 0 radius, CSS variable colors, monospace font.
 */

import { useRef, useState, useEffect, useCallback } from "react";
import { useClerk, useUser, useOrganization, useOrganizationList } from "@clerk/nextjs";
import { Component, type ReactNode } from "react";
import { LogOut, ChevronDown, Check, Plus } from "lucide-react";
import { useCreateTeam } from "@/lib/use-create-team";
import { PendingButton } from "@/components/ui/pending-button";

const LIST_MSG_CLASS = "px-3 py-2 text-[10px] text-[var(--color-text-dim)] tracking-wider font-mono";

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
  const {
    isLoaded: listLoaded,
    userMemberships,
    setActive,
  } = useOrganizationList({
    userMemberships: { infinite: true, pageSize: 50 },
  });

  const [open, setOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const [query, setQuery] = useState("");
  const [switching, setSwitching] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newTeamName, setNewTeamName] = useState("");
  const [switchError, setSwitchError] = useState<string | null>(null);

  const { loading: createLoading, error: createError, createTeam } = useCreateTeam();

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
      // Reset transient state when popover closes
      setQuery("");
      setSwitching(null);
      setShowCreate(false);
      setNewTeamName("");
      setSwitchError(null);
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

  async function handleSwitch(orgId: string) {
    if (!listLoaded || !setActive) return;
    if (orgId === organization?.id) { setOpen(false); return; }
    setSwitching(orgId);
    setSwitchError(null);
    try {
      await setActive({ organization: orgId });
      // Force full reload so gateway gets fresh JWT with new org_id
      window.location.href = "/dashboard";
      return;
    } catch (e) {
      setSwitchError(e instanceof Error ? e.message : String(e));
    } finally {
      setSwitching(null);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = newTeamName.trim();
    if (!trimmed) return;
    try {
      await createTeam(trimmed);
      // useCreateTeam already calls setActive internally — reload to pick up new org
      window.location.href = "/dashboard";
      return;
    } catch {
      // createError from hook will render
    }
  }

  const memberships = userMemberships.data ?? [];
  const q = query.trim().toLowerCase();
  const filtered = q
    ? memberships.filter((m) => m.organization.name.toLowerCase().includes(q))
    : memberships;

  // Derive target org name inline for aria-live
  const targetOrgName = switching
    ? memberships.find((m) => m.organization.id === switching)?.organization.name ?? switching
    : null;

  // Unified error: prefer switchError, then membership load error
  const listError = userMemberships.error
    ? (userMemberships.error instanceof Error
        ? userMemberships.error.message
        : String(userMemberships.error))
    : null;
  const displayError = switchError ?? listError;

  return (
    <div className="relative px-3 py-2 border-t border-[var(--color-border)]">
      {/* Trigger button */}
      <button
        ref={buttonRef}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="true"
        aria-expanded={open}
        className="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-[var(--color-bg-hover)] transition-colors text-left focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-inset"
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
          {/* aria-live region for switching announcements */}
          <span className="sr-only" aria-live="polite">
            {switching && targetOrgName ? `switching to ${targetOrgName}…` : ""}
          </span>

          {/* Current team + user info */}
          <div className="px-3 py-2.5 border-b border-[var(--color-border)]">
            <p className="text-[11px] text-[var(--color-text)] tracking-wider font-mono truncate" title={teamName}>
              {teamName}
            </p>
            <p className="text-[10px] text-[var(--color-text-dim)] tracking-wider font-mono truncate mt-0.5" title={email}>
              {email}
            </p>
          </div>

          {/* Search input — only when membership count > 10 */}
          {memberships.length > 10 && (
            <div className="px-3 pt-2 pb-1">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="filter teams"
                aria-label="Filter teams"
                autoComplete="off"
                spellCheck={false}
                className="w-full bg-transparent border border-[var(--color-border)] px-2 py-1 text-[11px] text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] font-mono tracking-wider focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]"
              />
            </div>
          )}

          {/* Unified error region — switch error or membership load error */}
          {displayError && (
            <p
              role="alert"
              className="px-3 py-1.5 text-[10px] text-[var(--color-error)] tracking-wider font-mono break-words"
            >
              {switchError ? `switch failed: ${displayError}` : `load error: ${displayError}`}
            </p>
          )}

          {/* Org list */}
          <div
            className="max-h-64 overflow-y-auto"
            aria-busy={!listLoaded || userMemberships.isLoading}
          >
            {!listLoaded || userMemberships.isLoading ? (
              <p className={LIST_MSG_CLASS}>
                loading teams…
              </p>
            ) : memberships.length === 0 && !organization ? (
              <p className={LIST_MSG_CLASS}>
                no teams yet. create one below
              </p>
            ) : filtered.length === 0 && q ? (
              <p className={LIST_MSG_CLASS}>
                no teams match &ldquo;{query}&rdquo;
              </p>
            ) : (
              <>
                {filtered.map((membership) => {
                  const org = membership.organization;
                  const isActive = org.id === organization?.id;
                  const isSwitching = switching === org.id;
                  return (
                    <button
                      key={org.id}
                      type="button"
                      onClick={() => handleSwitch(org.id)}
                      disabled={isSwitching}
                      aria-disabled={isSwitching}
                      aria-current={isActive ? "true" : undefined}
                      className={`w-full flex items-center gap-2 px-3 py-2 text-[11px] tracking-wider font-mono transition-colors focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-inset ${
                        isActive
                          ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
                          : "text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)]"
                      }`}
                    >
                      {/* Avatar */}
                      <span
                        className="flex-shrink-0 w-5 h-5 flex items-center justify-center bg-[var(--color-border)] text-[10px] font-mono text-[var(--color-text-muted)] uppercase"
                        aria-hidden="true"
                      >
                        {org.name.charAt(0)}
                      </span>
                      {/* Org name */}
                      <span className="flex-1 truncate text-left" title={org.name}>
                        {org.name}
                      </span>
                      {/* Active indicator */}
                      {isActive && (
                        <span className="flex-shrink-0 flex items-center">
                          <Check
                            size={10}
                            className="flex-shrink-0 text-[var(--color-text)]"
                            aria-hidden="true"
                          />
                          <span className="sr-only">active</span>
                        </span>
                      )}
                    </button>
                  );
                })}

                {/* Load-more row — only when no search query */}
                {userMemberships.hasNextPage && !q && (
                  <button
                    type="button"
                    onClick={() => userMemberships.fetchNext?.()}
                    disabled={userMemberships.isFetching}
                    className="w-full px-3 py-2 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] tracking-wider font-mono transition-colors text-left focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-inset"
                  >
                    {userMemberships.isFetching ? "loading…" : "load more"}
                  </button>
                )}
              </>
            )}
          </div>

          {/* Create-team CTA */}
          <div className="border-t border-[var(--color-border)]">
            {!showCreate ? (
              <button
                type="button"
                onClick={() => setShowCreate(true)}
                className="w-full flex items-center gap-2 px-3 py-2 text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] tracking-wider font-mono transition-colors focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-inset"
              >
                <Plus size={10} className="flex-shrink-0" aria-hidden="true" />
                create team
              </button>
            ) : (
              <div className="px-3 py-2 animate-slide-in-up">
                <form onSubmit={handleCreate} className="flex flex-col gap-2">
                  <input
                    type="text"
                    value={newTeamName}
                    onChange={(e) => setNewTeamName(e.target.value)}
                    placeholder="team name"
                    aria-label="New team name"
                    autoComplete="off"
                    className="w-full bg-transparent border border-[var(--color-border)] px-2 py-1 text-[11px] text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] font-mono tracking-wider focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]"
                  />
                  {createError && (
                    <p role="alert" className="text-[10px] text-[var(--color-error)] tracking-wider font-mono">
                      {createError}
                    </p>
                  )}
                  <div className="flex items-center gap-2">
                    <PendingButton type="submit" size="sm" pending={createLoading}>
                      create
                    </PendingButton>
                    <button
                      type="button"
                      onClick={() => { setShowCreate(false); setNewTeamName(""); }}
                      className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider font-mono transition-colors focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-inset px-2 py-1"
                    >
                      cancel
                    </button>
                  </div>
                </form>
              </div>
            )}
          </div>

          {/* Sign out */}
          <button
            onClick={handleSignOut}
            className="w-full flex items-center gap-2 px-3 py-2 text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] tracking-wider font-mono transition-colors border-t border-[var(--color-border)] focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-inset"
          >
            <LogOut size={10} aria-hidden="true" className="flex-shrink-0" />
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
