import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import styles from './PathCards.module.css';

export type PathCardProps = {
  title: string;
  description: string;
  to: string;
  icon: ReactNode;
  badge?: string;
  className?: string;
};

export function PathCard({title, description, to, icon, badge, className}: PathCardProps) {
  return (
    <Link to={to} className={clsx(styles.card, className)}>
      <span className={styles.icon} aria-hidden="true">
        {icon}
      </span>
      <span className={styles.text}>
        <span className={styles.titleRow}>
          <span className={styles.title}>{title}</span>
          {badge ? <span className={styles.badge}>{badge}</span> : null}
        </span>
        <span className={styles.description}>{description}</span>
      </span>
      <span className={styles.chevron} aria-hidden="true">
        <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 3.5 L10.5 8 L6 12.5" />
        </svg>
      </span>
    </Link>
  );
}

export type PathCardsProps = {
  children: ReactNode;
  className?: string;
  /** Column count at desktop. Defaults to 2. */
  columns?: 2 | 3 | 4;
};

export function PathCards({children, className, columns = 2}: PathCardsProps) {
  return (
    <div className={clsx(styles.grid, styles[`cols${columns}`], className)}>{children}</div>
  );
}

export default PathCards;
