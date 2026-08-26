import React, { type PropsWithChildren } from "react";

const style = {
  display: "contents",
};

/**
 * Adds the 'sp' className which serves as a namespace to its children,
 * so that the styles are scoped to the DOM subtree.
 */
export const StyleNamespace = React.forwardRef<
  HTMLDivElement,
  PropsWithChildren<{}>
>(({ children }, ref) => {
  return (
    <div ref={ref} className="sp" style={style}>
      {children}
    </div>
  );
});

StyleNamespace.displayName = "StyleNamespace";
