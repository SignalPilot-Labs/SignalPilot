"use client";

/**
 * Team name + slug edit section. Admin: editable FieldRows + save.
 * Non-admin: read-only. Save wraps organization.update in useReverification.
 */

import React, { useState } from "react";
import { Settings } from "lucide-react";
import { PendingButton } from "@/components/ui/pending-button";
import { useReverification } from "@clerk/nextjs";
import type { OrganizationResource } from "@clerk/types";
import { SectionHeader } from "@/components/ui/section-header";
import { useToast } from "@/components/ui/toast";
import {
  FIELD_INPUT_CLASS,
  LABEL_CLASS,
  ERROR_CLASS,
  NEUTRAL_CLASS,
} from "@/components/auth/auth-primitives";
import { isReverificationCancelledError } from "@/lib/security/use-reverify";
import { formatClerkError } from "@/lib/security/clerk-errors";
import type { TeamPermissions } from "@/lib/team/use-team-permissions";

export interface TeamOverviewSectionProps {
  org: OrganizationResource;
  perms: TeamPermissions;
}

export function TeamOverviewSection({ org, perms }: TeamOverviewSectionProps) {
  const { toast } = useToast();
  const [name, setName] = useState(org.name);
  const [slug, setSlug] = useState(org.slug ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const unchanged = name === org.name && slug === (org.slug ?? "");

  const reverifiedUpdate = useReverification(
    (params: { name: string; slug: string }) => org.update(params),
  );

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (unchanged) return;
    if (!name.trim()) { setError("team name is required"); return; }
    setError(null);
    setNotice(null);
    setSaving(true);
    try {
      await reverifiedUpdate({ name: name.trim(), slug: slug.trim() || undefined as unknown as string });
      toast("team updated", "success");
    } catch (err) {
      if (isReverificationCancelledError(err)) {
        setNotice("reverification required to update team");
      } else {
        setError(formatClerkError(err));
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="mb-8">
      <SectionHeader icon={Settings} title="overview" />
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
        {perms.canUpdate ? (
          <form onSubmit={handleSave} className="p-6 space-y-4">
            <div className="flex flex-col gap-1">
              <label htmlFor="team-name" className={LABEL_CLASS}>team name</label>
              <input
                id="team-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={FIELD_INPUT_CLASS}
                autoComplete="off"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="team-slug" className={LABEL_CLASS}>slug</label>
              <input
                id="team-slug"
                type="text"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                className={FIELD_INPUT_CLASS}
                autoComplete="off"
              />
            </div>

            <div role="alert" aria-live="assertive" aria-atomic="true">
              {error && <p className={ERROR_CLASS}>{error}</p>}
            </div>
            <div role="status" aria-live="polite" aria-atomic="true">
              {notice && <p className={NEUTRAL_CLASS}>{notice}</p>}
            </div>

            <PendingButton
              type="submit"
              pending={saving}
              pendingLabel="saving…"
              disabled={saving || unchanged}
            >
              save changes
            </PendingButton>
          </form>
        ) : (
          <div className="p-6 space-y-4">
            <div className="flex flex-col gap-1">
              <span className={LABEL_CLASS}>team name</span>
              <p className="text-[13px] text-[var(--color-text)] font-mono">{org.name}</p>
            </div>
            {org.slug && (
              <div className="flex flex-col gap-1">
                <span className={LABEL_CLASS}>slug</span>
                <p className="text-[13px] text-[var(--color-text)] font-mono">{org.slug}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
