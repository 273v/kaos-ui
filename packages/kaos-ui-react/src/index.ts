/**
 * @273v/kaos-ui-react — root barrel.
 *
 * Re-exports the public surface from every subpath so consumers can
 * `import { Composer, RunInspector } from "@273v/kaos-ui-react"` at
 * the cost of a wider tree-shake. Subpath imports
 * (`@273v/kaos-ui-react/chat`, `/debug`, etc.) are recommended for
 * production builds.
 */

export * from "./chat/index.js";
export * from "./debug/index.js";
export * from "./hooks/index.js";
export * from "./lib/index.js";
