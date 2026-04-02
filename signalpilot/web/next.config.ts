import type { NextConfig } from "next";

// Server-side gateway URL for rewrites (container-to-container).
// Falls back to Docker service name since rewrites run on the Next.js server, not the browser.
const GATEWAY_INTERNAL = process.env.SP_GATEWAY_INTERNAL_URL || "http://gateway:3300";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/gateway/:path*",
        destination: `${GATEWAY_INTERNAL}/:path*`,
      },
      // Proxy /api/* to gateway so tunnel access works without localhost
      {
        source: "/api/:path*",
        destination: `${GATEWAY_INTERNAL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
