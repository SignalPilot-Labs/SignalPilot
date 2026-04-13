import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/gateway/:path*",
        destination: `${process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
