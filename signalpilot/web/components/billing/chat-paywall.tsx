"use client";

import { MessageSquare } from "lucide-react";

export function ChatPaywall() {
  return (
    <div className="p-8 animate-fade-in">
      <div className="max-w-md mx-auto mt-24">
        <div className="flex items-center gap-3 mb-6">
          <MessageSquare className="w-6 h-6 text-[var(--color-text)]" />
          <h1 className="text-lg font-bold uppercase text-[var(--color-text)]">
            Data chat
          </h1>
        </div>
        <div className="border border-[var(--color-border)] p-6 space-y-4">
          <p className="text-sm text-[var(--color-text)]">
            Data chat is a Pro feature.
          </p>
          <p className="text-xs text-[var(--color-text-dim)] leading-relaxed">
            Upgrade to Pro, Team, or Enterprise to chat with your warehouse and
            dbt projects through a governed agent.
          </p>
          <a
            href="/settings/billing"
            className="inline-flex items-center gap-2 px-5 py-3 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium rounded-[10px] transition-colors duration-150 hover:opacity-90"
          >
            Upgrade plan
          </a>
        </div>
      </div>
    </div>
  );
}
