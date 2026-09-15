import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import styles from './LinkTiles.module.css';

export type LinkTileProps = {
  title: string;
  description?: string;
  to: string;
  eyebrow?: string;
  className?: string;
};

export function LinkTile({title, description, to, eyebrow, className}: LinkTileProps) {
  return (
    <Link to={to} className={clsx(styles.tile, className)}>
      <span className={styles.text}>
        {eyebrow ? <span className={styles.eyebrow}>{eyebrow}</span> : null}
        <span className={styles.title}>{title}</span>
        {description ? <span className={styles.description}>{description}</span> : null}
      </span>
      <svg
        className={styles.arrow}
        viewBox="0 0 16 16"
        width="14"
        height="14"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true">
        <path d="M3 8 H12.5 M9 4.5 L12.5 8 L9 11.5" />
      </svg>
    </Link>
  );
}

export type LinkTilesProps = {
  children: ReactNode;
  className?: string;
  /** Column count at desktop. Defaults to 2. */
  columns?: 1 | 2 | 3 | 4;
};

export function LinkTiles({children, className, columns = 2}: LinkTilesProps) {
  return <div className={clsx(styles.grid, styles[`cols${columns}`], className)}>{children}</div>;
}

export default LinkTiles;
