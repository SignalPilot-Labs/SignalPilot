import type { NextConfig } from "next";

// `output: "standalone"` exists only so Dockerfile.web can copy
// .next/standalone. Vercel builds its own serverless output and must not have
// it set: on Vercel the standalone copy step looks for
// .next/next-server.js.nft.json, which is not emitted there, and the build
// dies with ENOENT after "Running onBuildComplete".
const nextConfig: NextConfig = {
  output: process.env.VERCEL ? undefined : "standalone",
  poweredByHeader: false,
  serverExternalPackages: [
    "@tailwindcss/oxide",
    "lightningcss",
    "@tailwindcss/node",
  ],
  turbopack: {
    root: process.cwd(),
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
