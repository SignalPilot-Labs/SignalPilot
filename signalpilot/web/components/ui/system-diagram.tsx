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
        <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">system topology</span>
      </div>
      <div className="p-4 sm:p-6 flex items-center justify-center w-full overflow-x-auto">
        <svg className="w-full" style={{ minHeight: 280, maxHeight: 420 }} viewBox="0 0 680 280" fill="none" preserveAspectRatio="xMidYMid meet">
          {/* Agent/Client */}
          <g>
            <rect x="10" y="85" width="120" height="80" stroke="var(--color-border-hover)" strokeWidth="1.5" fill="var(--color-bg)" />
            <text x="70" y="118" textAnchor="middle" fill="var(--color-text-dim)" fontSize="13" fontFamily="monospace" letterSpacing="0.1em">AGENT</text>
            <text x="70" y="140" textAnchor="middle" fill="var(--color-text-dim)" fontSize="11" fontFamily="monospace" opacity="0.5">ai / client</text>
          </g>

          {/* Arrow: Agent → Gateway */}
          <g>
            <line x1="130" y1="125" x2="210" y2="125" stroke="var(--color-border-hover)" strokeWidth="1.5" strokeDasharray="6 4" />
            <path d="M205 119L214 125L205 131" stroke="var(--color-border-hover)" strokeWidth="1.5" fill="none" />
            {/* Flow dot */}
            <circle r="3.5" fill="var(--color-success)" opacity="0.6">
              <animateMotion dur="2s" repeatCount="indefinite" path="M130,125 L210,125" />
            </circle>
            <text x="170" y="114" textAnchor="middle" fill="var(--color-text-dim)" fontSize="10" fontFamily="monospace" opacity="0.5">SQL</text>
          </g>

          {/* Gateway (central) */}
          <g>
            <rect x="215" y="45" width="200" height="160" stroke={governanceActive ? "var(--color-success)" : "var(--color-border-hover)"} strokeWidth="1.5" fill="var(--color-bg-card)" />
            <rect x="215" y="45" width="200" height="32" fill="var(--color-bg-elevated)" />
            <text x="315" y="67" textAnchor="middle" fill="var(--color-text-muted)" fontSize="13" fontFamily="monospace" letterSpacing="0.12em">SIGNALPILOT</text>

            {/* Pipeline stages inside */}
            {["parse", "policy", "cost", "limit", "pii", "audit"].map((stage, i) => (
              <g key={stage}>
                <rect x={228 + i * 30} y={95} width={24} height={24} stroke="var(--color-border-hover)" strokeWidth="0.75" fill="var(--color-bg)" rx="0" />
                <text x={240 + i * 30} y={111} textAnchor="middle" fill={governanceActive ? "var(--color-success)" : "var(--color-text-dim)"} fontSize="9" fontFamily="monospace">
                  {String(i + 1).padStart(2, "0")}
                </text>
                <text x={240 + i * 30} y={134} textAnchor="middle" fill="var(--color-text-dim)" fontSize="7" fontFamily="monospace" opacity="0.5">
                  {stage}
                </text>
                {i < 5 && (
                  <line x1={252 + i * 30} y1={107} x2={258 + i * 30} y2={107} stroke="var(--color-border)" strokeWidth="0.75" />
                )}
              </g>
            ))}

            {/* Status */}
            <text x="315" y="165" textAnchor="middle" fill={governanceActive ? "var(--color-success)" : "var(--color-error)"} fontSize="10" fontFamily="monospace" letterSpacing="0.1em">
              {governanceActive ? "GOVERNANCE ACTIVE" : "GOVERNANCE OFF"}
            </text>
            <circle cx="270" cy="180" r="3.5" fill={governanceActive ? "var(--color-success)" : "var(--color-error)"}>
              {governanceActive && (
                <animate attributeName="opacity" values="1;0.3;1" dur="2s" repeatCount="indefinite" />
              )}
            </circle>
            <text x="283" y="184" fill="var(--color-text-dim)" fontSize="10" fontFamily="monospace">
              6 stages
            </text>
          </g>

          {/* Arrow: Gateway → Databases */}
          <g>
            <line x1="415" y1="100" x2="490" y2="72" stroke="var(--color-border-hover)" strokeWidth="1.5" strokeDasharray="6 4" />
            <path d="M484 66L493 72L484 78" stroke="var(--color-border-hover)" strokeWidth="1.5" fill="none" />
            <circle r="2.5" fill="var(--color-text-dim)" opacity="0.4">
              <animateMotion dur="2.5s" repeatCount="indefinite" path="M415,100 L490,72" />
            </circle>
          </g>

          {/* Arrow: Gateway → Sandboxes */}
          <g>
            <line x1="415" y1="155" x2="490" y2="185" stroke="var(--color-border-hover)" strokeWidth="1.5" strokeDasharray="6 4" />
            <path d="M484 179L493 185L484 191" stroke="var(--color-border-hover)" strokeWidth="1.5" fill="none" />
            <circle r="2.5" fill="var(--color-text-dim)" opacity="0.4">
              <animateMotion dur="3s" repeatCount="indefinite" path="M415,155 L490,185" />
            </circle>
          </g>

          {/* Databases */}
          <g>
            <rect x="490" y="30" width="120" height="80" stroke="var(--color-border-hover)" strokeWidth="1.5" fill="var(--color-bg)" />
            <ellipse cx="550" cy="46" rx="42" ry="10" stroke="var(--color-text-dim)" strokeWidth="1" fill="none" />
            <text x="550" y="88" textAnchor="middle" fill="var(--color-text-dim)" fontSize="13" fontFamily="monospace" letterSpacing="0.1em">
              DB × {connections}
            </text>
          </g>

          {/* Sandboxes */}
          <g>
            <rect x="490" y="150" width="120" height="80" stroke="var(--color-border-hover)" strokeWidth="1.5" fill="var(--color-bg)" strokeDasharray={activeSandboxes > 0 ? "none" : "4 4"} />
            <text x="550" y="180" textAnchor="middle" fill="var(--color-text-dim)" fontSize="12" fontFamily="monospace" letterSpacing="0.05em">
              {">"}_
            </text>
            <text x="550" y="210" textAnchor="middle" fill="var(--color-text-dim)" fontSize="13" fontFamily="monospace" letterSpacing="0.1em">
              VM × {activeSandboxes}
            </text>
          </g>

          {/* Arrow: Databases → Audit */}
          <g>
            <line x1="610" y1="70" x2="635" y2="120" stroke="var(--color-border)" strokeWidth="0.75" strokeDasharray="3 3" />
          </g>
          <g>
            <line x1="610" y1="190" x2="635" y2="140" stroke="var(--color-border)" strokeWidth="0.75" strokeDasharray="3 3" />
          </g>

          {/* Audit Store */}
          <g>
            <rect x="625" y="105" width="50" height="50" stroke="var(--color-border-hover)" strokeWidth="1.5" fill="var(--color-bg)" />
            <text x="650" y="130" textAnchor="middle" fill="var(--color-text-dim)" fontSize="11" fontFamily="monospace" letterSpacing="0.1em">AUDIT</text>
            <text x="650" y="146" textAnchor="middle" fill="var(--color-text-dim)" fontSize="8" fontFamily="monospace" opacity="0.5">JSONL</text>
          </g>
        </svg>
      </div>
    </div>
  );
}
