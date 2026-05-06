import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import { TanStackRouterVite } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Vite dev proxy notes (see kaos-ui PATTERNS.md):
// - The frontend dev server runs on :5173, the FastAPI backend on :8000.
// - We proxy /v1/* to the backend so cookies stay first-party (no CORS
//   in dev, even though the backend has CORS configured for prod).
// - cookieDomainRewrite + secure rewrites strip Domain= and the Secure
//   flag from Set-Cookie response headers so the browser actually
//   stores the cookie under the dev origin.

export default defineConfig({
  plugins: [
    // TanStack Router plugin must run BEFORE react() per its docs.
    TanStackRouterVite({
      target: "react",
      autoCodeSplitting: true,
    }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/v1": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        cookieDomainRewrite: { "*": "" },
        // Some dev setups send Secure cookies even on http; strip.
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes) => {
            const setCookie = proxyRes.headers["set-cookie"];
            if (setCookie) {
              proxyRes.headers["set-cookie"] = (
                Array.isArray(setCookie) ? setCookie : [setCookie]
              ).map((cookie) =>
                cookie.replace(/;\s*Secure/i, "").replace(/;\s*Domain=[^;]*/i, ""),
              );
            }
          });
        },
      },
    },
  },
  test: {
    environment: "happy-dom",
    setupFiles: ["./tests/setup.ts"],
    globals: true,
  },
});
