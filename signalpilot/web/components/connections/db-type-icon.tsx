export function DbTypeIcon({ type, size = 12 }: { type: string; size?: number }) {
  switch (type) {
    case "postgres":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <ellipse cx="6" cy="3" rx="4.5" ry="2" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <path d="M1.5 3V9C1.5 10.1 3.5 11 6 11C8.5 11 10.5 10.1 10.5 9V3" stroke="currentColor" strokeWidth="0.75" />
          <path d="M1.5 6C1.5 7.1 3.5 8 6 8C8.5 8 10.5 7.1 10.5 6" stroke="currentColor" strokeWidth="0.5" opacity="0.5" />
        </svg>
      );
    case "duckdb":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <circle cx="4.5" cy="5" r="0.8" fill="currentColor" />
          <path d="M4 7.5C4.5 8.5 7.5 8.5 8 7.5" stroke="currentColor" strokeWidth="0.75" strokeLinecap="round" fill="none" />
          <path d="M7.5 4L9 3.5" stroke="currentColor" strokeWidth="0.75" strokeLinecap="round" />
        </svg>
      );
    case "mysql":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <path d="M2 2L6 10L10 2" stroke="currentColor" strokeWidth="0.75" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          <line x1="4" y1="6" x2="8" y2="6" stroke="currentColor" strokeWidth="0.75" />
        </svg>
      );
    case "snowflake":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <line x1="6" y1="1" x2="6" y2="11" stroke="currentColor" strokeWidth="0.75" />
          <line x1="1.7" y1="3.5" x2="10.3" y2="8.5" stroke="currentColor" strokeWidth="0.75" />
          <line x1="1.7" y1="8.5" x2="10.3" y2="3.5" stroke="currentColor" strokeWidth="0.75" />
          <circle cx="6" cy="6" r="1.5" stroke="currentColor" strokeWidth="0.5" fill="none" />
        </svg>
      );
    case "bigquery":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <rect x="2" y="2" width="8" height="8" rx="1" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <path d="M4 5L6 8L8 5" stroke="currentColor" strokeWidth="0.75" fill="none" strokeLinecap="round" />
          <circle cx="6" cy="4" r="1" stroke="currentColor" strokeWidth="0.5" fill="none" />
        </svg>
      );
    case "redshift":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <path d="M6 1L10.5 3.5V8.5L6 11L1.5 8.5V3.5L6 1Z" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <line x1="6" y1="6" x2="6" y2="11" stroke="currentColor" strokeWidth="0.5" opacity="0.5" />
          <line x1="6" y1="6" x2="10.5" y2="3.5" stroke="currentColor" strokeWidth="0.5" opacity="0.5" />
          <line x1="6" y1="6" x2="1.5" y2="3.5" stroke="currentColor" strokeWidth="0.5" opacity="0.5" />
        </svg>
      );
    case "clickhouse":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <rect x="2" y="1" width="1.5" height="10" fill="currentColor" opacity="0.8" />
          <rect x="4.5" y="3" width="1.5" height="8" fill="currentColor" opacity="0.6" />
          <rect x="7" y="1" width="1.5" height="10" fill="currentColor" opacity="0.4" />
          <rect x="9.5" y="5" width="1.5" height="6" fill="currentColor" opacity="0.3" />
        </svg>
      );
    case "databricks":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <path d="M6 1L11 3.5L6 6L1 3.5L6 1Z" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <path d="M1 6L6 8.5L11 6" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <path d="M1 8.5L6 11L11 8.5" stroke="currentColor" strokeWidth="0.75" fill="none" />
        </svg>
      );
    case "mssql":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <rect x="1.5" y="2" width="9" height="8" rx="1" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <path d="M3.5 5L5 7L8.5 4" stroke="currentColor" strokeWidth="0.75" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </svg>
      );
    case "trino":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <path d="M4 4L6 8L8 4" stroke="currentColor" strokeWidth="0.75" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </svg>
      );
    case "xata":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <line x1="6" y1="2" x2="6" y2="10" stroke="currentColor" strokeWidth="0.75" />
          <path d="M6 4C4.5 2.5 2 2.5 2 4.5C2 6 4 6.5 6 6" stroke="currentColor" strokeWidth="0.75" fill="none" strokeLinecap="round" />
          <path d="M6 4C7.5 2.5 10 2.5 10 4.5C10 6 8 6.5 6 6" stroke="currentColor" strokeWidth="0.75" fill="none" strokeLinecap="round" />
          <path d="M6 6C4.5 6 3 7 3 8.5C3 9.5 5 9.5 6 8" stroke="currentColor" strokeWidth="0.5" opacity="0.6" fill="none" strokeLinecap="round" />
          <path d="M6 6C7.5 6 9 7 9 8.5C9 9.5 7 9.5 6 8" stroke="currentColor" strokeWidth="0.5" opacity="0.6" fill="none" strokeLinecap="round" />
        </svg>
      );
    case "sqlite":
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <rect x="3" y="1" width="6" height="10" rx="1" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <line x1="4.5" y1="4" x2="7.5" y2="4" stroke="currentColor" strokeWidth="0.5" opacity="0.5" />
          <line x1="4.5" y1="6" x2="7.5" y2="6" stroke="currentColor" strokeWidth="0.5" opacity="0.5" />
          <line x1="4.5" y1="8" x2="7.5" y2="8" stroke="currentColor" strokeWidth="0.5" opacity="0.5" />
        </svg>
      );
    default:
      return (
        <svg width={size} height={size} viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <rect x="1.5" y="1.5" width="9" height="9" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <circle cx="6" cy="6" r="2" stroke="currentColor" strokeWidth="0.5" fill="none" />
        </svg>
      );
  }
}

