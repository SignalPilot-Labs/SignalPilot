"use client";

import Link from "next/link";
import type { ComponentProps } from "react";
import { str } from "./attrs";

/**
 * In-app hrefs (root-relative, e.g. the agent's /lineage/<model> deep links)
 * render as next/link soft navigations so clicking one keeps the SPA alive;
 * everything else opens in a new tab with rel=noopener.
 */
export function MarkdownLink({
  children,
  href,
  title,
}: ComponentProps<"a"> & { node?: unknown }) {
  const url = str(href);
  if (url.startsWith("/") && !url.startsWith("//")) {
    return (
      <Link href={url} title={title}>
        {children}
      </Link>
    );
  }
  return (
    <a href={url} title={title} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}
