import type { NextConfig } from "next";

const GATEWAY_INTERNAL = process.env.SP_GATEWAY_INTERNAL_URL || "http://gateway:3300";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/gateway/:path*",
        destination: `${GATEWAY_INTERNAL}/:path*`,
      },
      {
        source: "/api/:path*",
        destination: `${GATEWAY_INTERNAL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
