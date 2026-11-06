import type { NextConfig } from "next";

// /api/* and /files/* are proxied to the backend by route handlers (src/app/api, src/app/files),
// which read API_URL at request time.
const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
};

export default nextConfig;
