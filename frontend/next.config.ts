import type { NextConfig } from "next";

/** Set on Railway at build time — proxies /api/* to backend (no browser CORS). */
const backendUrl = (
  process.env.BACKEND_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000"
).replace(/\/$/, "");

const nextConfig: NextConfig = {
  async redirects() {
    return [
      { source: "/strategies", destination: "/strategy-lab", permanent: false },
      { source: "/more", destination: "/menu", permanent: false },
      { source: "/leaderboard", destination: "/analytics", permanent: false },
      { source: "/live-lab/certification", destination: "/paper-trading/certification", permanent: false },
      { source: "/live-lab/:runId", destination: "/paper-trading/:runId", permanent: false },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;