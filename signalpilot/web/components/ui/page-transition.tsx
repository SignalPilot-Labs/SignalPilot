"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState, useRef } from "react";

/**
 * Wraps page content with a smooth fade+slide transition on route change.
 * Uses pathname as key to trigger re-animation.
 */
export function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [displayChildren, setDisplayChildren] = useState(children);
  const [transitioning, setTransitioning] = useState(false);
  const prevPathname = useRef(pathname);

  useEffect(() => {
    if (pathname !== prevPathname.current) {
      setTransitioning(true);
      // Brief exit, then swap content and enter
      const timeout = setTimeout(() => {
        setDisplayChildren(children);
        setTransitioning(false);
        prevPathname.current = pathname;
      }, 100);
      return () => clearTimeout(timeout);
    } else {
      setDisplayChildren(children);
    }
  }, [pathname, children]);

  return (
    <div
      className={`transition-all duration-200 ease-out ${
        transitioning
          ? "opacity-0 translate-y-1"
          : "opacity-100 translate-y-0"
      }`}
    >
      {displayChildren}
    </div>
  );
}
