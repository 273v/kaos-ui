// Library — types, event handler, transport provider, markdown.

export type {
  ChatMessage,
  MessageRole,
  PlanSnapshot,
  PlanStep,
  ToolCallSummary,
  ToolPolicySnapshot,
  TurnStatusKind,
} from "./chat-state.js";
export { newId } from "./chat-state.js";
export type { Citation, ExtractCitationsResponse } from "./citations.js";
export { extractCitations } from "./citations.js";

export type { TranscriptState } from "./event-handler.js";
export {
  applyEvent,
  clearCapabilityRequest,
  initialState,
  markAborted,
  pushUserAndAssistantPlaceholder,
} from "./event-handler.js";
export type {
  BudgetExceededEvent,
  CitationFoundEvent,
  EventType,
  EvidenceInsufficientEvent,
  GroundingRefusalEvent,
  IntentClassifiedEvent,
  KaosAgentEvent,
  MemoryEventEvent,
  PlanProposedEvent,
  RunErrorEvent,
  SpanEvent,
  SpanPhase,
  SpanSubject,
  TextDeltaEvent,
  ThinkingDeltaEvent,
  ToolCallApprovalRequiredEvent,
  ToolCallArgsDeltaEvent,
  ToolPolicyDecidedEvent,
  TurnSummaryEvent,
  UsageObservedEvent,
} from "./events.js";
export { ALL_EVENT_TYPES } from "./events.js";
export type {
  FileListResponse,
  FileMeta,
  FileParseStatus,
  UploadResponse,
} from "./files.js";
export { DEFAULT_UPLOAD_ACCEPT, deleteFile, listFiles, uploadFile } from "./files.js";
export { renderMarkdown } from "./markdown.js";
export type { KaosQueryKey } from "./query-keys.js";
export { kaosQueryKeys } from "./query-keys.js";
export type { ReadSseStreamOptions, StreamEvent } from "./streaming.js";
export { readSseStream } from "./streaming.js";
export { stripScratchpadTags } from "./text-strip.js";
export type { ApiError, KaosUIProviderProps, Transport } from "./transport.js";
export {
  joinUrl,
  KaosUIProvider,
  transportFetch,
  transportJson,
  useTransport,
} from "./transport.js";
export type {
  ListVfsOptions,
  VfsListResponse,
  VfsNode,
  VfsNodeKind,
} from "./vfs.js";
export { groupVfsNodes, listSessionVfs } from "./vfs.js";
