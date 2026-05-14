import { defineConfig } from "@hey-api/openapi-ts";

// Generates a typed client from the FastAPI backend's OpenAPI spec.
// Run with `pnpm codegen` after the backend's docs are exposed.
//
// The backend serves /v1/openapi.json in dev (env != production). In
// CI you can also point this at a static `openapi.json` checked in to
// the repo, which keeps the build offline.
export default defineConfig({
  client: "@hey-api/client-fetch",
  input: "http://127.0.0.1:8000/v1/openapi.json",
  output: {
    path: "src/api/client",
    format: "biome",
    lint: "biome",
  },
  plugins: [
    "@hey-api/typescript",
    "@hey-api/sdk",
    {
      name: "@tanstack/react-query",
      // Generates queryOptions / mutation helpers that compose with
      // TanStack Query primitives (useQuery, useMutation, prefetch).
    },
  ],
});
