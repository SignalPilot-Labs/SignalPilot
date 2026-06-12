/* oxlint-disable typescript/no-explicit-any */
declare module "*.svg" {
  const content: string | undefined;
  export default content;
}

declare module "*.svg?inline" {
  const content: string;
  export default content;
}

// Raw-loader CSS imports (Turbopack rule in next.config.ts converts these to strings).
// Without this declaration TS sees `typeof import("*.css")` and breaks `cssStyles: string[]`.
declare module "*.css" {
  const content: string;
  export default content;
}

// Swiper publishes CSS files without TS types under these subpath module names.
declare module "swiper/css";
declare module "swiper/css/navigation";
declare module "swiper/css/pagination";
declare module "swiper/css/scrollbar";
declare module "swiper/css/virtual";

// Stricter lib types
interface Body {
  json<T = unknown>(): Promise<T>;
}

// Stricter lib types
interface JSON {
  parse(
    text: string,
    reviver?: (this: any, key: string, value: any) => any,
  ): unknown;

  rawJSON(value: string): unknown;
}

// Improve type inference for Array.filter with BooleanConstructor
interface Array<T> {
  filter(predicate: BooleanConstructor): NonNullable<T>[];
}
