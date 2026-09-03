"use client";

import Link from "next/link";
import {
  lazy,
  Suspense,
  useCallback,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";
import { isPlainLeftClick, type LineageHref } from "./lineage-href";

// Lazy: the chat bundle must not pay for reactflow + dagre until a lineage
// link is actually clicked.
const LineageModal = lazy(() =>
  import("./lineage-modal").then((module) => ({ default: module.LineageModal })),
);

/**
 * A chat link to /lineage/<model>?project=<id>. A plain left click opens the
 * lineage modal over the chat; modifier and middle clicks keep the browser's
 * open-in-new-tab behavior, and the href stays a real route for copy-link.
 */
export function LineageLink({
  link,
  title,
  children,
}: {
  link: LineageHref;
  title?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!isPlainLeftClick(event)) return;
    event.preventDefault();
    setOpen(true);
  };
  return (
    <>
      <Link
        href={link.href}
        title={title}
        onClick={onClick}
        data-lineage-model={link.modelName}
      >
        {children}
      </Link>
      {open && (
        <Suspense fallback={null}>
          <LineageModal link={link} onClose={close} />
        </Suspense>
      )}
    </>
  );
}
