import type { NextConfig } from "next";

/**
 * Where the frontend server forwards API calls.
 *
 * In Docker this is the backend's service name on the internal Docker network.
 * Running on a developer's machine it is the local FastAPI process, which is
 * also the default, so nothing has to be configured for `npm run dev`.
 *
 * Next.js fixes rewrite destinations during `next build`, so in Docker this is
 * supplied as a build argument rather than only as a run-time variable.
 */
const BACKEND_INTERNAL_URL =
  process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  /**
   * Bundle a self-contained server at build time.
   *
   * This is what lets the Docker image run the application without installing
   * npm packages at run time. It changes nothing about `npm run dev` or
   * `npm start` on a developer's machine.
   */
  output: "standalone",

  /**
   * The API proxy.
   *
   * The browser calls this application's own origin — /api/v1/... — and Next.js
   * forwards the request to the backend over the internal Docker network. The
   * browser never learns the backend's address.
   *
   * Two things follow from that, and both matter for a local Docker install:
   *
   *   - There is no cross-origin request, so no CORS configuration to get wrong.
   *   - The application works at whatever address it is opened on — localhost,
   *     127.0.0.1, the machine's name on the network — because no backend
   *     address was ever baked into the JavaScript.
   *
   * On a developer's machine the frontend's API client talks to the backend
   * directly (NEXT_PUBLIC_API_URL defaults to http://127.0.0.1:8000), so this
   * rewrite is simply unused. Both paths reach the same FastAPI routes.
   */
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_INTERNAL_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
