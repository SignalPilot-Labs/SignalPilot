import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "SignalPilot · Self-Improving AI Agent",
  description:
    "CEO, PM, and Engineer agents collaborate in an autonomous loop — planning improvements, writing code, running tests, and shipping PRs. Every cycle makes your codebase better.",
  openGraph: {
    title: "SignalPilot · Self-Improving AI Agent",
    description:
      "Software that improves itself. Autonomous agents that plan, code, test, and ship — 24/7.",
    type: "website",
  },
};

export default function LandingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="!overflow-auto" style={{ height: "auto", overflow: "auto" }}>
      <style>{`
        html, body { height: auto !important; overflow: auto !important; }

        /* Animated gradient border for terminal blocks */
        .terminal-glow {
          position: relative;
        }
        .terminal-glow::before {
          content: "";
          position: absolute;
          inset: -1px;
          background: linear-gradient(
            var(--angle, 0deg),
            transparent 40%,
            rgba(0, 255, 136, 0.15) 50%,
            transparent 60%
          );
          z-index: -1;
          animation: rotate-gradient 6s linear infinite;
        }
        @keyframes rotate-gradient {
          0% { --angle: 0deg; }
          100% { --angle: 360deg; }
        }
        @property --angle {
          syntax: "<angle>";
          initial-value: 0deg;
          inherits: false;
        }

        /* Smooth scroll */
        html { scroll-behavior: smooth; }

        /* Selection color */
        ::selection {
          background: rgba(0, 255, 136, 0.2);
          color: white;
        }

        /* Ensure content is visible even before framer-motion hydrates */
        @media (prefers-reduced-motion: reduce) {
          [style*="opacity: 0"] { opacity: 1 !important; }
          [style*="transform"] { transform: none !important; }
        }
      `}</style>
      {children}
    </div>
  );
}
