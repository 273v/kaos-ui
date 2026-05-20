// Hooks — useSendMessage, useCitations, useCostAggregation, useFileUpload.

export type {
  DebugEvent,
  UseSendMessageOptions,
  UseSendMessageResult,
} from "./use-send-message.js";
export { useSendMessage } from "./use-send-message.js";

export {
  useBackfillFiles,
  useDeleteFile,
  useSessionFiles,
  useUploadFile,
} from "./use-files.js";

export type { UseCitationsResult } from "./use-citations.js";
export { useCitations } from "./use-citations.js";

export type { ModelUsage, UseCostAggregationResult } from "./use-cost-aggregation.js";
export { useCostAggregation } from "./use-cost-aggregation.js";

export { useLocalStorage } from "./use-local-storage.js";

export type { ActiveRunPointer } from "./use-active-run.js";
export { useActiveRun } from "./use-active-run.js";

// Re-export the transport-context reader from the lib layer so hook
// consumers can import it from `@273v/kaos-ui-react/hooks` without
// crossing subpath barriers.
export { useTransport } from "../lib/transport.js";
