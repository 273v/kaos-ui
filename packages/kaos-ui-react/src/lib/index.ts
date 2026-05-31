// Library — types, event handler, transport provider, markdown.

export type {
  MessageRole,
  ToolCallSummary,
  ToolPolicySnapshot,
  ChatMessage,
  TurnStatusKind,
  PlanStep,
  PlanSnapshot,
} from "./chat-state.js";
export { newId } from "./chat-state.js";

export type {
  SpanSubject,
  SpanPhase,
  SpanEvent,
  TextDeltaEvent,
  ThinkingDeltaEvent,
  ToolCallArgsDeltaEvent,
  IntentClassifiedEvent,
  PlanProposedEvent,
  CitationFoundEvent,
  UsageObservedEvent,
  EvidenceInsufficientEvent,
  GroundingRefusalEvent,
  TurnSummaryEvent,
  MemoryEventEvent,
  RunErrorEvent,
  BudgetExceededEvent,
  ToolCallApprovalRequiredEvent,
  ToolPolicyDecidedEvent,
  KaosAgentEvent,
  EventType,
} from "./events.js";
export { ALL_EVENT_TYPES } from "./events.js";

export type { TranscriptState } from "./event-handler.js";
export {
  applyEvent,
  initialState,
  pushUserAndAssistantPlaceholder,
  markAborted,
  clearCapabilityRequest,
} from "./event-handler.js";

export type { Transport, ApiError, KaosUIProviderProps } from "./transport.js";
export {
  KaosUIProvider,
  useTransport,
  joinUrl,
  transportFetch,
  transportJson,
} from "./transport.js";

export { renderMarkdown } from "./markdown.js";

export type { StreamEvent, ReadSseStreamOptions } from "./streaming.js";
export { readSseStream } from "./streaming.js";

export type {
  FileParseStatus,
  FileMeta,
  UploadResponse,
  FileListResponse,
} from "./files.js";
export { uploadFile, listFiles, deleteFile, DEFAULT_UPLOAD_ACCEPT } from "./files.js";

export type {
  VfsNode,
  VfsNodeKind,
  VfsListResponse,
  ListVfsOptions,
} from "./vfs.js";
export { listSessionVfs, groupVfsNodes } from "./vfs.js";

export type { Citation, ExtractCitationsResponse } from "./citations.js";
export { extractCitations } from "./citations.js";

export type { KaosQueryKey } from "./query-keys.js";
export { kaosQueryKeys } from "./query-keys.js";

export { stripScratchpadTags } from "./text-strip.js";
