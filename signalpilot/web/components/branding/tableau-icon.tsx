import type { SVGProps } from "react";

/** A plain plus-cluster glyph for Tableau. Not the brand mark. */
export function TableauIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeWidth="1.7"
      aria-hidden="true"
      {...props}
    >
      <path d="M12 7v10M7 12h10" />
      <path d="M12 2.5v3M10.5 4h3" />
      <path d="M12 18.5v3M10.5 20h3" />
      <path d="M2.5 12h3M4 10.5v3" />
      <path d="M18.5 12h3M20 10.5v3" />
    </svg>
  );
}
