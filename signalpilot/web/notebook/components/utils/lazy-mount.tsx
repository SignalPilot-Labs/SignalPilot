import React, { type ActivityProps, type PropsWithChildren } from "react";

// React 19 exports `Activity` as a symbol-typed component. Some bundlers
// (webpack/Next.js) cannot resolve it as a named ESM export from the CJS
// react shim. Access it via the namespace object instead so the import
// is always resolved at runtime through the module default export.
const Activity = (
  React as typeof React & { Activity: React.ComponentType<ActivityProps> }
).Activity;

interface Props {
  isOpen: boolean;
}

/**
 * Lazy-mount until it is open for the first time
 */
export const LazyMount: React.FC<PropsWithChildren<Props>> = ({
  isOpen,
  children,
}) => {
  const [hasMountedBefore, setHasMountedBefore] = React.useState(false);

  if (isOpen && !hasMountedBefore) {
    setHasMountedBefore(true);
  }

  return hasMountedBefore || isOpen ? children : null;
};

/**
 * Wraps a component in an Activity component. It is not mounted until it is open for the first time.
 */
export const LazyActivity: React.FC<PropsWithChildren<ActivityProps>> = (
  props,
) => {
  const [hasMountedBefore, setHasMountedBefore] = React.useState(false);

  if (props.mode === "visible" && !hasMountedBefore) {
    setHasMountedBefore(true);
  }

  if (hasMountedBefore) {
    return <Activity {...props} />;
  }

  return null;
};
