import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import styles from './PageHero.module.css';

export type PageHeroAction = {
  label: string;
  to: string;
  primary?: boolean;
};

export type PageHeroProps = {
  eyebrow?: string;
  title: ReactNode;
  lede?: ReactNode;
  illustration?: ReactNode;
  actions?: PageHeroAction[];
  className?: string;
  /** Use `h1` on a landing page, `div` when the page already has its own h1. */
  as?: 'h1' | 'h2' | 'div';
  /** Paint the quiet --sp-band behind the hero, full-bleed. */
  band?: boolean;
};

export function PageHero({
  eyebrow,
  title,
  lede,
  illustration,
  actions,
  className,
  as = 'h1',
  band = true,
}: PageHeroProps) {
  const Heading = as;
  return (
    <section className={clsx(styles.hero, band && styles.band, illustration && styles.withArt, className)}>
      <div className={styles.inner}>
        <div className={styles.copy}>
          {eyebrow ? <p className={styles.eyebrow}>{eyebrow}</p> : null}
          <Heading className={styles.title}>{title}</Heading>
          {lede ? <p className={styles.lede}>{lede}</p> : null}
          {actions && actions.length ? (
            <div className={styles.actions}>
              {actions.map((a) => (
                <Link
                  key={a.label}
                  to={a.to}
                  className={clsx(styles.action, a.primary ? styles.primary : styles.secondary)}>
                  {a.label}
                  {a.primary ? (
                    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M3 8 H12.5 M9 4.5 L12.5 8 L9 11.5" />
                    </svg>
                  ) : null}
                </Link>
              ))}
            </div>
          ) : null}
        </div>
        {illustration ? (
          <div className={styles.art} aria-hidden="true">
            {illustration}
          </div>
        ) : null}
      </div>
    </section>
  );
}

export default PageHero;
