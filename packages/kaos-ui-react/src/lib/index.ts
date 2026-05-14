// Library — types, event handler, transport provider, markdown.

export type {
  MessageRole,
  ToolCallSummary,
  ChatMessage,
  TurnStatus,
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
