import { copyFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "tsup";

// Build: ESM + CJS + d.ts for every subpath, plus the standalone styles
// + tailwind preset that consumers wire into their app config.
//
// We use `tsup` (esbuild under the hood) instead of Vite library mode
// because tsup handles multi-entry + per-entry .d.ts generation in one
// invocation and integrates with the subpath `exports` in package.json
// without a config split.
export default defineConfig({
  entry: {
    index: "src/index.ts",
    "chat/index": "src/chat/index.ts",
    "debug/index": "src/debug/index.ts",
    "hooks/index": "src/hooks/index.ts",
    "lib/index": "src/lib/index.ts",
    "tailwind.preset": "src/tailwind.preset.ts",
  },
  format: ["esm", "cjs"],
  dts: true,
  splitting: false,
  sourcemap: false,
  clean: true,
  treeshake: true,
  // React + react-dom + TanStack Query are peer deps; never bundle them.
  external: [
    "react",
    "react-dom",
    "react/jsx-runtime",
    "@tanstack/react-query",
    "tailwindcss",
  ],
  // Copy the static CSS (theme tokens + markdown + jsontree styles)
  // into dist/ so the `./styles.css` subpath export resolves to a
  // real file in the published tarball.
  onSuccess: async () => {
    mkdirSync(resolve("dist"), { recursive: true });
    copyFileSync(
      resolve("src/theme/tokens.css"),
      resolve("dist/styles.css"),
    );
  },
});
