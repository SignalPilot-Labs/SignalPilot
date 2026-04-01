export default function Loading() {
  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-center">
        {/* Animated loading SVG — stacked concentric shapes */}
        <svg width="64" height="64" viewBox="0 0 64 64" fill="none" className="mx-auto mb-5">
          {/* Outer frame with draw-in */}
          <rect x="2" y="2" width="60" height="60" stroke="var(--color-border)" strokeWidth="1" fill="none">
            <animate attributeName="stroke-dasharray" values="0 248;248 0;248 0" dur="1.5s" repeatCount="indefinite" />
          </rect>

          {/* Middle rotating square */}
          <rect x="16" y="16" width="32" height="32" stroke="var(--color-text-dim)" strokeWidth="0.75" fill="none" opacity="0.4">
            <animateTransform
              attributeName="transform"
              type="rotate"
              from="0 32 32"
              to="360 32 32"
              dur="8s"
              repeatCount="indefinite"
            />
          </rect>

          {/* Inner counter-rotating square */}
          <rect x="22" y="22" width="20" height="20" stroke="var(--color-text-dim)" strokeWidth="0.5" fill="none" opacity="0.25">
            <animateTransform
              attributeName="transform"
              type="rotate"
              from="360 32 32"
              to="0 32 32"
              dur="6s"
              repeatCount="indefinite"
            />
          </rect>

          {/* Center pulsing dot */}
          <circle cx="32" cy="32" r="2" fill="var(--color-success)">
            <animate attributeName="r" values="1.5;3;1.5" dur="1.5s" repeatCount="indefinite" />
            <animate attributeName="opacity" values="0.8;0.3;0.8" dur="1.5s" repeatCount="indefinite" />
          </circle>

          {/* Orbiting dots */}
          <circle r="1" fill="var(--color-text-dim)" opacity="0.4">
            <animateMotion dur="3s" repeatCount="indefinite" path="M32,12 A20,20 0 1,1 31.99,12" />
          </circle>
          <circle r="1" fill="var(--color-text-dim)" opacity="0.25">
            <animateMotion dur="3s" begin="1.5s" repeatCount="indefinite" path="M32,12 A20,20 0 1,1 31.99,12" />
          </circle>

          {/* Corner brackets */}
          <path d="M2 8V2H8" stroke="var(--color-border-hover)" strokeWidth="1" />
          <path d="M56 2H62V8" stroke="var(--color-border-hover)" strokeWidth="1" />
          <path d="M62 56V62H56" stroke="var(--color-border-hover)" strokeWidth="1" />
          <path d="M8 62H2V56" stroke="var(--color-border-hover)" strokeWidth="1" />
        </svg>

        <p className="text-[10px] text-[var(--color-text-dim)] tracking-[0.2em] uppercase">
          loading
        </p>
        <div className="mt-2 w-16 h-px mx-auto overflow-hidden">
          <div className="h-full bg-[var(--color-text-dim)] animate-data-flow" />
        </div>
      </div>
    </div>
  );
}
