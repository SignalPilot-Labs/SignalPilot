import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  typescript: { ignoreBuildErrors: true },
  serverExternalPackages: [
    "@tailwindcss/oxide",
    "lightningcss",
    "@tailwindcss/node",
  ],
  turbopack: {
    resolveAlias: {
      "vscode-jsonrpc/lib/common/cancellation.js":
        "vscode-jsonrpc/lib/common/cancellation",
      "vscode-jsonrpc/lib/common/events.js":
        "vscode-jsonrpc/lib/common/events",
    },
    rules: {
      "**/@glideapps/glide-data-grid/dist/index.css": {
        loaders: ["raw-loader"],
        as: "*.js",
      },
      "**/plugins/impl/matrix.css": { loaders: ["raw-loader"], as: "*.js" },
      "**/swiper/swiper.css": { loaders: ["raw-loader"], as: "*.js" },
      "**/swiper/modules/navigation.css": { loaders: ["raw-loader"], as: "*.js" },
      "**/swiper/modules/pagination.css": { loaders: ["raw-loader"], as: "*.js" },
      "**/swiper/modules/scrollbar.css": { loaders: ["raw-loader"], as: "*.js" },
      "**/swiper/modules/virtual.css": { loaders: ["raw-loader"], as: "*.js" },
      "**/components/slides/slides.css": { loaders: ["raw-loader"], as: "*.js" },
      "**/components/slides/swiper-slides.css": { loaders: ["raw-loader"], as: "*.js" },
      "**/*.svg": { loaders: ["raw-loader"], as: "*.js" },
    },
  },
};

export default nextConfig;
