import {useEffect, useRef, useState} from 'react';
import clsx from 'clsx';
import styles from './FieldTable.module.css';

export type FieldRow = {
  label: string;
  value: string;
  /** Render the value in JetBrains Mono (URLs, tokens, commands). */
  mono?: boolean;
  /** Show a copy button. Defaults to true when `mono` is set. */
  copy?: boolean;
  note?: string;
};

export type FieldTableProps = {
  rows: FieldRow[];
  /** Optional caption shown above the table as a mono eyebrow. */
  caption?: string;
  className?: string;
};

function CopyButton({value, label}: {value: string; label: string}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable (insecure context) — leave the button as is */
    }
  }

  return (
    <button
      type="button"
      className={clsx(styles.copy, copied && styles.copied)}
      onClick={copy}
      aria-label={copied ? `Copied ${label}` : `Copy ${label}`}
      aria-live="polite">
      {copied ? (
        <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M3.5 8.5 L6.5 11.5 L12.5 5" />
        </svg>
      ) : (
        <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="5.5" y="5.5" width="8" height="8" rx="1.8" />
          <path d="M10.5 5.5 V4 a1.5 1.5 0 0 0 -1.5 -1.5 H4 a1.5 1.5 0 0 0 -1.5 1.5 V9 a1.5 1.5 0 0 0 1.5 1.5 H5.5" />
        </svg>
      )}
      <span>{copied ? 'Copied' : 'Copy'}</span>
    </button>
  );
}

export function FieldTable({rows, caption, className}: FieldTableProps) {
  return (
    <div className={clsx(styles.wrap, className)}>
      {caption ? <div className={styles.caption}>{caption}</div> : null}
      <dl className={styles.table}>
        {rows.map((row) => {
          const showCopy = row.copy ?? Boolean(row.mono);
          return (
            <div className={styles.row} key={row.label}>
              <dt className={styles.label}>{row.label}</dt>
              <dd className={styles.cell}>
                <div className={styles.valueRow}>
                  <span className={clsx(styles.value, row.mono && styles.mono)}>{row.value}</span>
                  {showCopy ? <CopyButton value={row.value} label={row.label} /> : null}
                </div>
                {row.note ? <div className={styles.note}>{row.note}</div> : null}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}

export default FieldTable;
