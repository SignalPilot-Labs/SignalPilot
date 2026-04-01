"use client";

export function EmptyTerminal() {
  return (
    <svg width="120" height="80" viewBox="0 0 120 80" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ animation: "float 6s ease-in-out infinite" }}>
      {/* Terminal window */}
      <rect x="10" y="8" width="100" height="64" rx="4" stroke="rgba(255,255,255,0.08)" strokeWidth="1" />
      {/* Title bar */}
      <line x1="10" y1="20" x2="110" y2="20" stroke="rgba(255,255,255,0.06)" strokeWidth="1" />
      <circle cx="20" cy="14" r="2" fill="rgba(255,68,68,0.4)" />
      <circle cx="28" cy="14" r="2" fill="rgba(255,170,0,0.4)" />
      <circle cx="36" cy="14" r="2" fill="rgba(0,255,136,0.4)" />
      {/* Terminal prompt */}
      <text x="18" y="34" fill="rgba(0,255,136,0.3)" fontSize="8" fontFamily="monospace">$</text>
      <rect x="26" y="28" width="40" height="8" rx="1" fill="rgba(255,255,255,0.04)" />
      {/* Cursor blink */}
      <rect x="68" y="28" width="6" height="8" rx="1" fill="rgba(0,255,136,0.2)" style={{ animation: "blink 1s step-end infinite" }} />
      {/* Output lines */}
      <rect x="18" y="42" width="60" height="4" rx="1" fill="rgba(255,255,255,0.03)" />
      <rect x="18" y="50" width="45" height="4" rx="1" fill="rgba(255,255,255,0.02)" />
      <rect x="18" y="58" width="55" height="4" rx="1" fill="rgba(255,255,255,0.02)" />
      {/* Scan line */}
      <rect x="10" y="20" width="100" height="2" fill="rgba(0,255,136,0.03)" style={{ animation: "scan-line 4s linear infinite" }} />
    </svg>
  );
}

export function EmptyEvents() {
  return (
    <div className="flex flex-col items-center gap-4 py-12">
      <EmptyTerminal />
      <div className="text-center space-y-1.5">
        <p className="text-[11px] text-[#777] font-medium">Waiting for events</p>
        <p className="text-[10px] text-[#444]">Select a run or start a new one to see live activity</p>
      </div>
    </div>
  );
}

export function EmptyRuns() {
  return (
    <div className="flex flex-col items-center gap-3 py-8 px-4">
      <svg width="48" height="48" viewBox="0 0 48 48" fill="none" style={{ animation: "float 6s ease-in-out infinite" }}>
        <rect x="8" y="6" width="32" height="36" rx="3" stroke="rgba(255,255,255,0.08)" strokeWidth="1" />
        <line x1="14" y1="16" x2="34" y2="16" stroke="rgba(255,255,255,0.04)" strokeWidth="1" />
        <line x1="14" y1="22" x2="34" y2="22" stroke="rgba(255,255,255,0.04)" strokeWidth="1" />
        <line x1="14" y1="28" x2="28" y2="28" stroke="rgba(255,255,255,0.04)" strokeWidth="1" />
        <circle cx="36" cy="36" r="8" stroke="rgba(0,255,136,0.2)" strokeWidth="1" strokeDasharray="3 2" />
        <line x1="36" y1="33" x2="36" y2="39" stroke="rgba(0,255,136,0.3)" strokeWidth="1" />
        <line x1="33" y1="36" x2="39" y2="36" stroke="rgba(0,255,136,0.3)" strokeWidth="1" />
      </svg>
      <div className="text-center space-y-1">
        <p className="text-[10px] text-[#777]">No runs yet</p>
        <p className="text-[9px] text-[#444]">Start an improvement run to begin</p>
      </div>
    </div>
  );
}
