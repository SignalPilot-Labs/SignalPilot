import type { SVGProps } from "react";

export function NotionIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <rect x="4" y="3.5" width="16" height="17" rx="1.5" strokeWidth="1.7" />
      <path
        d="M8.25 16.25v-8.5h2.05l3.4 5.6v-5.6h2.05v8.5H13.7l-3.4-5.6v5.6H8.25Z"
        fill="currentColor"
        stroke="none"
      />
    </svg>
  );
}
