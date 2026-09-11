import {Children, isValidElement, type ReactNode} from 'react';
import clsx from 'clsx';
import useBaseUrl from '@docusaurus/useBaseUrl';
import styles from './Steps.module.css';

export type StepProps = {
  title: ReactNode;
  children?: ReactNode;
  /** Inline SVG or any node shown beside the step at desktop, stacked on mobile. */
  illustration?: ReactNode;
  /** Screenshot path (goes through <img>). Rendered like `illustration` if both given, image wins. */
  image?: string;
  imageAlt?: string;
  /** Injected by <Steps>; you never set this yourself. */
  index?: number;
};

export function Step({title, children, illustration, image, imageAlt, index}: StepProps) {
  const imageSrc = useBaseUrl(image ?? '');
  const aside = image ? (
    <figure className={styles.figure}>
      <img src={imageSrc} alt={imageAlt ?? ''} loading="lazy" />
    </figure>
  ) : illustration ? (
    <div className={styles.illustration}>{illustration}</div>
  ) : null;

  return (
    <li className={clsx(styles.step, aside && styles.hasAside)}>
      <div className={styles.marker} aria-hidden="true">
        <span className={styles.number}>{index}</span>
      </div>
      <div className={styles.body}>
        <h3 className={clsx(styles.title, "sp-step-title")}>{title}</h3>
        {children ? <div className={styles.content}>{children}</div> : null}
      </div>
      {aside ? <div className={styles.aside}>{aside}</div> : null}
    </li>
  );
}

export type StepsProps = {
  children: ReactNode;
  className?: string;
  /** Start numbering from a value other than 1. */
  start?: number;
};

export function Steps({children, className, start = 1}: StepsProps) {
  let n = start - 1;
  const items = Children.map(children, (child) => {
    if (!isValidElement<StepProps>(child)) return child;
    n += 1;
    return <Step {...child.props} index={n} key={child.key ?? n} />;
  });
  return (
    <ol className={clsx(styles.steps, className)} start={start}>
      {items}
    </ol>
  );
}

export default Steps;
