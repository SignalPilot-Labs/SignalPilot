"use client";

/**
 * Animated SVG grid background — subtle, developer-aesthetic backdrop
 * Renders an infinite grid with occasional highlight pulses at intersections.
 */
export function GridBackground() {
  return (
    <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden opacity-[0.035]" aria-hidden="true">
      <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
        <defs>
          {/* Base grid pattern */}
          <pattern id="grid-sm" width="24" height="24" patternUnits="userSpaceOnUse">
            <path d="M24 0V24M0 24H24" stroke="currentColor" strokeWidth="0.5" fill="none" />
          </pattern>
          <pattern id="grid-lg" width="96" height="96" patternUnits="userSpaceOnUse">
            <rect width="96" height="96" fill="url(#grid-sm)" />
            <path d="M96 0V96M0 96H96" stroke="currentColor" strokeWidth="1" fill="none" />
          </pattern>
          {/* Radial fade mask so edges dissolve */}
          <radialGradient id="grid-fade" cx="50%" cy="40%" r="60%">
            <stop offset="0%" stopColor="white" stopOpacity="1" />
            <stop offset="100%" stopColor="white" stopOpacity="0" />
          </radialGradient>
          <mask id="grid-mask">
            <rect width="100%" height="100%" fill="url(#grid-fade)" />
          </mask>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid-lg)" mask="url(#grid-mask)" />
        {/* Occasional pulse dots at intersections */}
        {[
          { cx: "25%", cy: "20%", delay: "0s" },
          { cx: "75%", cy: "35%", delay: "2s" },
          { cx: "50%", cy: "60%", delay: "4s" },
          { cx: "30%", cy: "80%", delay: "1s" },
          { cx: "80%", cy: "70%", delay: "3s" },
        ].map((dot, i) => (
          <circle key={i} cx={dot.cx} cy={dot.cy} r="1" fill="currentColor">
            <animate attributeName="r" values="1;3;1" dur="6s" begin={dot.delay} repeatCount="indefinite" />
            <animate attributeName="opacity" values="0.3;0.8;0.3" dur="6s" begin={dot.delay} repeatCount="indefinite" />
          </circle>
        ))}
      </svg>
    </div>
  );
}

/**
 * Crosshair cursor overlay — appears at intersection points on hover
 * Use sparingly; best for hero sections or landing.
 */
export function ScanlineOverlay() {
  return (
    <div className="pointer-events-none fixed inset-0 z-[1] overflow-hidden" aria-hidden="true">
      <div
        className="absolute inset-0"
        style={{
          background: "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(255,255,255,0.008) 2px, rgba(255,255,255,0.008) 4px)",
        }}
      />
    </div>
  );
}
