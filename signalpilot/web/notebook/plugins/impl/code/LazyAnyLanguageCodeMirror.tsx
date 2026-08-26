import { lazy } from "react";

export const LazyAnyLanguageCodeMirror = lazy(
  () => import("./any-language-editor"),
);
