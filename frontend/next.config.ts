import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

// Production is a static export served by FastAPI on the same origin.
// In dev, /api is proxied to BACKEND_URL (default :8000); rewrites are not allowed with export.
const nextConfig: NextConfig = {
  output: isDev ? undefined : "export",
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  ...(isDev && {
    async rewrites() {
      return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
    },
  }),
};

export default nextConfig;
