import type { NextConfig } from "next";

// The browser talks only to Next.js; /api/* is proxied to Django on the same origin,
// so the API needs no CORS. Rewrites are fixed at build time (see the Dockerfile).
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
