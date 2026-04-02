export function SignalPilotLogo() {
  return (
    <div className="relative">
      {/* Status ring */}
      <svg width="38" height="38" viewBox="0 0 38 38" fill="none" className="absolute -inset-[3px]">
        <circle cx="19" cy="19" r="17" stroke="var(--color-border)" strokeWidth="0.5" fill="none" />
        <circle cx="19" cy="19" r="17" stroke="var(--color-success)" strokeWidth="1" fill="none"
          strokeDasharray="80 27" strokeLinecap="square" opacity="0.3"
          className="-rotate-90 origin-center"
        >
          <animateTransform attributeName="transform" type="rotate" from="0 19 19" to="360 19 19" dur="20s" repeatCount="indefinite" />
        </circle>
      </svg>
      <svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
        {/* Outer frame */}
        <rect x="1" y="1" width="30" height="30" fill="white" />
        <rect x="2" y="2" width="28" height="28" fill="black" />
        {/* Terminal chevron */}
        <path
          d="M8 9L14 16L8 23"
          stroke="white"
          strokeWidth="2.5"
          strokeLinecap="square"
          strokeLinejoin="miter"
        />
        {/* Cursor line */}
        <line x1="16" y1="23" x2="24" y2="23" stroke="white" strokeWidth="2.5" strokeLinecap="square" />
        {/* Signal dot with pulse */}
        <circle cx="24" cy="9" r="3" fill="#00ff88" opacity="0.15">
          <animate attributeName="r" values="3;5;3" dur="3s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.15;0;0.15" dur="3s" repeatCount="indefinite" />
        </circle>
        <circle cx="24" cy="9" r="2" fill="#00ff88" />
      </svg>
    </div>
  );
}

export function SignalPilotLogoSmall() {
  return (
    <svg width="24" height="24" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="1" y="1" width="30" height="30" fill="white" />
      <rect x="2" y="2" width="28" height="28" fill="black" />
      <path d="M8 9L14 16L8 23" stroke="white" strokeWidth="2.5" strokeLinecap="square" strokeLinejoin="miter" />
      <line x1="16" y1="23" x2="24" y2="23" stroke="white" strokeWidth="2.5" strokeLinecap="square" />
      <circle cx="24" cy="9" r="2" fill="#00ff88" />
    </svg>
  );
}
