"use client";

export function GridBackground() {
  return (
    <div className="fixed inset-0 pointer-events-none z-0" aria-hidden>
      <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
        <defs>
          {/* Small grid */}
          <pattern
            id="grid-sm"
            width="24"
            height="24"
            patternUnits="userSpaceOnUse"
          >
            <path
              d="M 24 0 L 0 0 0 24"
              fill="none"
              stroke="rgba(255,255,255,0.02)"
              strokeWidth="0.5"
            />
          </pattern>
          {/* Large grid */}
          <pattern
            id="grid-lg"
            width="96"
            height="96"
            patternUnits="userSpaceOnUse"
          >
            <path
              d="M 96 0 L 0 0 0 96"
              fill="none"
              stroke="rgba(255,255,255,0.03)"
              strokeWidth="0.5"
            />
          </pattern>
          {/* Radial fade mask */}
          <radialGradient id="grid-fade" cx="50%" cy="50%" r="60%">
            <stop offset="0%" stopColor="white" stopOpacity="1" />
            <stop offset="100%" stopColor="white" stopOpacity="0" />
          </radialGradient>
          <mask id="grid-mask">
            <rect width="100%" height="100%" fill="url(#grid-fade)" />
          </mask>
        </defs>
        <g mask="url(#grid-mask)">
          <rect width="100%" height="100%" fill="url(#grid-sm)" />
          <rect width="100%" height="100%" fill="url(#grid-lg)" />
        </g>
        {/* Pulse dots at intersections */}
        {[
          { cx: "25%", cy: "30%", delay: 0 },
          { cx: "75%", cy: "20%", delay: 2 },
          { cx: "50%", cy: "60%", delay: 4 },
          { cx: "15%", cy: "80%", delay: 1 },
          { cx: "85%", cy: "70%", delay: 3 },
        ].map((dot, i) => (
          <circle
            key={i}
            cx={dot.cx}
            cy={dot.cy}
            r="1"
            fill="rgba(0, 255, 136, 0.15)"
            style={{
              animation: `pulse-dot 6s ease-in-out ${dot.delay}s infinite`,
            }}
          />
        ))}
      </svg>
    </div>
  );
}
