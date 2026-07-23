"use client";

/**
 * Barely-there backdrop — a wide-spaced grid at near-invisible opacity plus a
 * faint radial mint glow, matching the landing page aesthetic. Static (no
 * marquee/pulse animation) so it never competes with content.
 */
export function GridBackground() {
  return (
    <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden" aria-hidden="true">
      {/* Faint radial mint glow, top-center like the landing page hero */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 80% 50% at 50% -10%, rgba(0,255,136,0.04), transparent 70%)",
        }}
      />
      <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg" className="opacity-[0.018]">
        <defs>
          {/* Wide-spaced base grid */}
          <pattern id="grid-lg" width="96" height="96" patternUnits="userSpaceOnUse">
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
          background: "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(255,255,255,0.003) 2px, rgba(255,255,255,0.003) 4px)",
        }}
      />
    </div>
  );
}
