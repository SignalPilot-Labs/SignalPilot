import { Children, isValidElement, type ReactNode } from "react";

export function str(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return fallback;
}

/** Drops the hast `node` Streamdown passes to overrides, leaving DOM props. */
export function domProps<T extends { node?: unknown }>(props: T): Omit<T, "node"> {
  const copy: T = { ...props };
  delete (copy as { node?: unknown }).node;
  return copy;
}

/** Flattens a React subtree back to its text, for code and diagram sources. */
export function childText(children: ReactNode): string {
  let out = "";
  Children.forEach(children, (child) => {
    if (child == null || typeof child === "boolean") return;
    if (typeof child === "string" || typeof child === "number") {
      out += child;
      return;
    }
    if (isValidElement<{ children?: ReactNode }>(child)) {
      out += childText(child.props.children);
    }
  });
  return out;
}
