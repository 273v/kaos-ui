// Hooks — useSendMessage, useCitations, useCostAggregation, useFileUpload.

// Re-export the transport-context reader from the lib layer so hook
// consumers can import it from `@273v/kaos-ui-react/hooks` without
// crossing subpath barriers.
export { useTransport } from "../lib/transport.js";
export type { ActiveRunPointer } from "./use-active-run.js";
export { useActiveRun } from "./use-active-run.js";

export type { UseCitationsResult } from "./use-citations.js";
export { useCitations } from "./use-citations.js";

export type { ModelUsage, UseCostAggregationResult } from "./use-cost-aggregation.js";
export { useCostAggregation } from "./use-cost-aggregation.js";
export {
  useBackfillFiles,
  useDeleteFile,
  useSessionFiles,
  useUploadFile,
} from "./use-files.js";
export { useLocalStorage } from "./use-local-storage.js";
export type {
  DebugEvent,
  UseSendMessageOptions,
  UseSendMessageResult,
} from "./use-send-message.js";
export { useSendMessage } from "./use-send-message.js";
export type { UseSessionVfsOptions } from "./use-vfs.js";
export { useSessionVfs } from "./use-vfs.js";
