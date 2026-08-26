import React from "react";

export const LazyVegaEmbed = React.lazy(() =>
  import("react-vega").then((m) => ({ default: m.VegaEmbed })),
);
