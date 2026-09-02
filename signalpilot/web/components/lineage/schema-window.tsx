"use client";

/** Schema explorer window — database.schema groups with model rows. */

import { ChevronDown, ChevronRight } from "lucide-react";
import React, { useState } from "react";

import { LAYER_COLOR, matGlyph } from "./palette";
import type { ParsedMap } from "./parse-map";

export function SchemaWindow({
  parsed,
  query,
  selectedId,
  onSelect,
}: {
  parsed: ParsedMap;
  query: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const q = query.trim().toLowerCase();

  return (
    <div className="flex h-full w-60 shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-bg-card)]/60">
      <div className="border-b border-[var(--color-border)] px-3 py-2 text-[10px] uppercase tracking-[0.1em] text-[var(--color-text-dim)]">
        schemas
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        {[...parsed.schemas.entries()].map(([schema, ids]) => {
          const rows = q
            ? ids.filter((id) => parsed.models.get(id)!.name.toLowerCase().includes(q))
            : ids;
          if (q && rows.length === 0) return null;
          const isCollapsed = collapsed.has(schema) && !q;
          return (
            <div key={schema}>
              <button
                type="button"
                onClick={() =>
                  setCollapsed((prev) => {
                    const next = new Set(prev);
                    if (next.has(schema)) next.delete(schema);
                    else next.add(schema);
                    return next;
                  })
                }
                className="flex w-full items-center gap-1 px-2 py-1.5 text-left text-[11px] text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
              >
                {isCollapsed ? <ChevronRight className="h-3 w-3 shrink-0" /> : <ChevronDown className="h-3 w-3 shrink-0" />}
                <span className="truncate font-mono">{schema}</span>
                <span className="ml-auto text-[9px] text-[var(--color-text-dim)]">{rows.length}</span>
              </button>
              {!isCollapsed &&
                rows.map((id) => {
                  const m = parsed.models.get(id)!;
                  const active = id === selectedId;
                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => onSelect(id)}
                      className={`flex w-full items-center gap-1.5 py-[3px] pl-7 pr-2 text-left font-mono text-[10.5px] leading-tight transition-colors ${
                        active
                          ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
                          : "text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)]/60 hover:text-[var(--color-text)]"
                      }`}
                    >
                      <span
                        className="h-1.5 w-1.5 shrink-0 rounded-[2px]"
                        style={{ background: LAYER_COLOR[m.layer] }}
                        aria-hidden="true"
                      />
                      <span className="w-3 shrink-0 text-center text-[9px]" style={{ color: LAYER_COLOR[m.layer] }} aria-hidden="true">
                        {matGlyph(m.materialized, m.layer)}
                      </span>
                      <span className="truncate">{m.name}</span>
                    </button>
                  );
                })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
