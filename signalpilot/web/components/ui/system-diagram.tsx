"use client";

/**
 * SVG system topology diagram — shows the SignalPilot architecture
 * with animated data flow between components.
 */
export function SystemDiagram({
  connections = 0,
  activeSandboxes = 0,
  governanceActive = true,
}: {
  connections?: number;
  activeSandboxes?: number;
  governanceActive?: boolean;
}) {
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
      <div className="px-4 py-2.5 border-b border-[var(--color-border)] flex items-center gap-2">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <rect x="1" y="1" width="4" height="4" stroke="var(--color-text-dim)" strokeWidth="0.75" />
          <rect x="7" y="1" width="4" height="4" stroke="var(--color-text-dim)" strokeWidth="0.75" />
          <rect x="4" y="7" width="4" height="4" stroke="var(--color-text-dim)" strokeWidth="0.75" />
          <line x1="5" y1="5" x2="5" y2="7" stroke="var(--color-text-dim)" strokeWidth="0.5" />
          <line x1="7" y1="5" x2="7" y2="7" stroke="var(--color-text-dim)" strokeWidth="0.5" />
        </svg>
        <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">system topology</span>
      </div>
      <div className="p-4 sm:p-6 overflow-x-auto">
        <svg viewBox="0 0 480 140" fill="none" className="mx-auto w-full" style={{ maxWidth: "480px" }}>
          {/* Agent/Client */}
          <g>
            <rect x="0" y="45" width="80" height="50" stroke="var(--color-border-hover)" strokeWidth="1" fill="var(--color-bg)" />
            <text x="40" y="66" textAnchor="middle" fill="var(--color-text-dim)" fontSize="8" fontFamily="monospace" letterSpacing="0.1em">AGENT</text>
            <text x="40" y="80" textAnchor="middle" fill="var(--color-text-dim)" fontSize="7" fontFamily="monospace" opacity="0.5">ai / client</text>
          </g>

          {/* Arrow: Agent → Gateway */}
          <g>
            <line x1="80" y1="70" x2="140" y2="70" stroke="var(--color-border-hover)" strokeWidth="1" strokeDasharray="4 3" />
            <path d="M136 66L142 70L136 74" stroke="var(--color-border-hover)" strokeWidth="1" fill="none" />
            {/* Flow dot */}
            <circle r="2" fill="var(--color-success)" opacity="0.6">
              <animateMotion dur="2s" repeatCount="indefinite" path="M80,70 L140,70" />
            </circle>
            <text x="110" y="62" textAnchor="middle" fill="var(--color-text-dim)" fontSize="6" fontFamily="monospace" opacity="0.5">SQL</text>
          </g>

          {/* Gateway (central) */}
          <g>
            <rect x="140" y="30" width="120" height="80" stroke={governanceActive ? "var(--color-success)" : "var(--color-border-hover)"} strokeWidth="1" fill="var(--color-bg-card)" />
            <rect x="140" y="30" width="120" height="18" fill="var(--color-bg-elevated)" />
            <text x="200" y="43" textAnchor="middle" fill="var(--color-text-muted)" fontSize="8" fontFamily="monospace" letterSpacing="0.1em">SIGNALPILOT</text>

            {/* Pipeline stages inside */}
            {["parse", "policy", "cost", "limit", "pii", "audit"].map((stage, i) => (
              <g key={stage}>
                <rect x={148 + i * 18} y={56} width={14} height={14} stroke="var(--color-border-hover)" strokeWidth="0.5" fill="var(--color-bg)" rx="0" />
                <text x={155 + i * 18} y={66} textAnchor="middle" fill={governanceActive ? "var(--color-success)" : "var(--color-text-dim)"} fontSize="5" fontFamily="monospace">
                  {String(i + 1).padStart(2, "0")}
                </text>
                {i < 5 && (
                  <line x1={162 + i * 18} y1={63} x2={166 + i * 18} y2={63} stroke="var(--color-border)" strokeWidth="0.5" />
                )}
              </g>
            ))}

            {/* Status */}
            <text x="200" y="90" textAnchor="middle" fill={governanceActive ? "var(--color-success)" : "var(--color-error)"} fontSize="6" fontFamily="monospace" letterSpacing="0.1em">
              {governanceActive ? "GOVERNANCE ACTIVE" : "GOVERNANCE OFF"}
            </text>
            <circle cx="165" cy="98" r="2" fill={governanceActive ? "var(--color-success)" : "var(--color-error)"}>
              {governanceActive && (
                <animate attributeName="opacity" values="1;0.3;1" dur="2s" repeatCount="indefinite" />
              )}
            </circle>
            <text x="175" y="100" fill="var(--color-text-dim)" fontSize="6" fontFamily="monospace">
              6 stages
            </text>
          </g>

          {/* Arrow: Gateway → Databases */}
          <g>
            <line x1="260" y1="55" x2="320" y2="40" stroke="var(--color-border-hover)" strokeWidth="1" strokeDasharray="4 3" />
            <path d="M316 36L322 40L316 44" stroke="var(--color-border-hover)" strokeWidth="1" fill="none" />
            <circle r="1.5" fill="var(--color-text-dim)" opacity="0.4">
              <animateMotion dur="2.5s" repeatCount="indefinite" path="M260,55 L320,40" />
            </circle>
          </g>

          {/* Arrow: Gateway → Sandboxes */}
          <g>
            <line x1="260" y1="85" x2="320" y2="100" stroke="var(--color-border-hover)" strokeWidth="1" strokeDasharray="4 3" />
            <path d="M316 96L322 100L316 104" stroke="var(--color-border-hover)" strokeWidth="1" fill="none" />
            <circle r="1.5" fill="var(--color-text-dim)" opacity="0.4">
              <animateMotion dur="3s" repeatCount="indefinite" path="M260,85 L320,100" />
            </circle>
          </g>

          {/* Databases */}
          <g>
            <rect x="320" y="15" width="80" height="50" stroke="var(--color-border-hover)" strokeWidth="1" fill="var(--color-bg)" />
            <ellipse cx="360" cy="25" rx="30" ry="6" stroke="var(--color-text-dim)" strokeWidth="0.75" fill="none" />
            <text x="360" y="50" textAnchor="middle" fill="var(--color-text-dim)" fontSize="8" fontFamily="monospace" letterSpacing="0.1em">
              DB × {connections}
            </text>
          </g>

          {/* Sandboxes */}
          <g>
            <rect x="320" y="80" width="80" height="50" stroke="var(--color-border-hover)" strokeWidth="1" fill="var(--color-bg)" strokeDasharray={activeSandboxes > 0 ? "none" : "3 3"} />
            <text x="360" y="100" textAnchor="middle" fill="var(--color-text-dim)" fontSize="7" fontFamily="monospace" letterSpacing="0.05em">
              {">"}_
            </text>
            <text x="360" y="118" textAnchor="middle" fill="var(--color-text-dim)" fontSize="8" fontFamily="monospace" letterSpacing="0.1em">
              VM × {activeSandboxes}
            </text>
          </g>

          {/* Arrow: Databases → Audit */}
          <g>
            <line x1="400" y1="40" x2="430" y2="70" stroke="var(--color-border)" strokeWidth="0.5" strokeDasharray="2 2" />
          </g>
          <g>
            <line x1="400" y1="100" x2="430" y2="70" stroke="var(--color-border)" strokeWidth="0.5" strokeDasharray="2 2" />
          </g>

          {/* Audit Store */}
          <g>
            <rect x="420" y="55" width="55" height="30" stroke="var(--color-border-hover)" strokeWidth="1" fill="var(--color-bg)" />
            <text x="447" y="72" textAnchor="middle" fill="var(--color-text-dim)" fontSize="7" fontFamily="monospace" letterSpacing="0.1em">AUDIT</text>
            <text x="447" y="82" textAnchor="middle" fill="var(--color-text-dim)" fontSize="5" fontFamily="monospace" opacity="0.5">JSONL</text>
          </g>
        </svg>
      </div>
    </div>
  );
}
