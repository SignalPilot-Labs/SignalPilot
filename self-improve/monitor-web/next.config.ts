import type { NextConfig } from "next";

// Server-side rewrite target: Docker service name for container-to-container,
// falls back to localhost for local dev outside Docker.
const API_INTERNAL = process.env.API_INTERNAL_URL || process.env.API_URL || "http://localhost:3401";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_INTERNAL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
