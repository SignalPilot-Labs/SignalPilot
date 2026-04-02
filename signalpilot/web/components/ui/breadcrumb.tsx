"use client";

import Link from "next/link";

/**
 * Terminal-style breadcrumb navigation.
 * Shows as: ~/signalpilot/path > subpath
 */
export function Breadcrumb({
  items,
}: {
  items: { label: string; href?: string }[];
}) {
  return (
    <nav className="flex items-center gap-1.5 text-[12px] tracking-wider mb-4">
      {items.map((item, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 && (
            <svg
              width="8"
              height="8"
              viewBox="0 0 8 8"
              fill="none"
              className="text-[var(--color-text-dim)]"
            >
              <path
                d="M3 2L5 4L3 6"
                stroke="currentColor"
                strokeWidth="1"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
          {item.href ? (
            <Link
              href={item.href}
              className="text-[var(--color-text-dim)] hover:text-[var(--color-text)] active:text-[var(--color-text)] transition-colors hover-underline py-1 -my-1"
            >
              {item.label}
            </Link>
          ) : (
            <span className="text-[var(--color-text-muted)]">{item.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
