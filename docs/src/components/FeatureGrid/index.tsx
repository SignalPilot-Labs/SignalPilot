import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import styles from './FeatureGrid.module.css';

export type FeatureCardProps = {
  title: string;
  description: string;
  to: string;
  illustration: ReactNode;
  className?: string;
};

export function FeatureCard({title, description, to, illustration, className}: FeatureCardProps) {
  return (
    <Link to={to} className={clsx(styles.card, className)}>
      <span className={styles.art} aria-hidden="true">
        {illustration}
      </span>
      <span className={styles.text}>
        <span className={styles.title}>{title}</span>
        <span className={styles.description}>{description}</span>
        <span className={styles.more}>
          Learn more
          <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M3 8 H12.5 M9 4.5 L12.5 8 L9 11.5" />
          </svg>
        </span>
      </span>
    </Link>
  );
}

export type FeatureGridProps = {
  children: ReactNode;
  className?: string;
  /** Column count at desktop. Defaults to 3. */
  columns?: 2 | 3;
};

export function FeatureGrid({children, className, columns = 3}: FeatureGridProps) {
  return <div className={clsx(styles.grid, styles[`cols${columns}`], className)}>{children}</div>;
}

export default FeatureGrid;
