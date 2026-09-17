import type {ReactNode} from 'react';
import clsx from 'clsx';
import styles from './Callout.module.css';

export type CalloutKind = 'tip' | 'note' | 'warning' | 'security';

export type CalloutProps = {
  kind?: CalloutKind;
  title?: string;
  children: ReactNode;
  className?: string;
};

const DEFAULT_TITLE: Record<CalloutKind, string> = {
  tip: 'Tip',
  note: 'Note',
  warning: 'Heads up',
  security: 'Security',
};

function Glyph({kind}: {kind: CalloutKind}) {
  const common = {
    viewBox: '0 0 20 20',
    width: 16,
    height: 16,
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.6,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };
  switch (kind) {
    case 'tip':
      // small bulb
      return (
        <svg {...common}>
          <path d="M7 15 h6 M8 17.5 h4" />
          <path d="M10 2.5 a5 5 0 0 0 -3 9 c0.6 0.6 1 1.2 1 2 h4 c0 -0.8 0.4 -1.4 1 -2 a5 5 0 0 0 -3 -9 z" />
        </svg>
      );
    case 'warning':
      // rounded triangle with mark
      return (
        <svg {...common}>
          <path d="M10 3 L17.5 16 H2.5 Z" />
          <path d="M10 8 v4 M10 14.3 v0.2" />
        </svg>
      );
    case 'security':
      // shield
      return (
        <svg {...common}>
          <path d="M10 2 L16.5 4.6 V9.5 C16.5 13.8 13.8 16.9 10 18 C6.2 16.9 3.5 13.8 3.5 9.5 V4.6 Z" />
          <path d="M7.3 10.2 L9.2 12.1 L12.8 8.4" />
        </svg>
      );
    default:
      // circle with i
      return (
        <svg {...common}>
          <circle cx="10" cy="10" r="7.5" />
          <path d="M10 9 v5 M10 6.2 v0.2" />
        </svg>
      );
  }
}

export function Callout({kind = 'note', title, children, className}: CalloutProps) {
  return (
    <aside className={clsx(styles.callout, styles[kind], className)} role="note">
      <div className={styles.head}>
        <span className={styles.glyph}>
          <Glyph kind={kind} />
        </span>
        <span className={styles.title}>{title ?? DEFAULT_TITLE[kind]}</span>
      </div>
      <div className={styles.body}>{children}</div>
    </aside>
  );
}

export default Callout;
