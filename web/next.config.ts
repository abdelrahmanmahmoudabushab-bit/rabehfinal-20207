import type { NextConfig } from "next";

const API_URL = process.env.API_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // The browser only talks to Next; Next forwards /api/* to the FastAPI backend (no CORS, one origin).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
