// Chat surface — composer, message transcript, file upload UI,
// citations side panel, model picker.

export { Composer } from "./Composer.js";
export type { ComposerProps } from "./Composer.js";
export { Message } from "./Message.js";
export { TurnStatus } from "./TurnStatus.js";
export { ToolCallBlock } from "./ToolCallBlock.js";
export { PlanCard } from "./PlanCard.js";
export { JsonView } from "./JsonView.js";
export { formatToolCall, repairAndParseJson, toolLabel } from "./tool-formatters.js";
export type { FormattedToolCall, ResultKind } from "./tool-formatters.js";
export { UsageChip } from "./UsageChip.js";
export { DropZone } from "./DropZone.js";
export { FileChips } from "./FileChips.js";
export { CitationsPanel } from "./CitationsPanel.js";
export { DocumentExplorer } from "./DocumentExplorer.js";
export type { AskAboutSelection } from "./DocumentExplorer.js";
export { ModelPicker } from "./ModelPicker.js";
export type { ModelEntry } from "./ModelPicker.js";
export { ToolPolicyBadge } from "./ToolPolicyBadge.js";
// AgenticLoop UI surface (kaos-agents 0.1.0a4):
export { GoalCheckBadge } from "./GoalCheckBadge.js";
export { ElevationPill } from "./ElevationPill.js";
export { CapabilityApproval } from "./CapabilityApproval.js";
export type { CapabilityDecision } from "./CapabilityApproval.js";
export { LoopTerminatedBanner } from "./LoopTerminatedBanner.js";
export { ReasoningSummary } from "./ReasoningSummary.js";
export { SlashMenu } from "./SlashMenu.js";
export type { Skill, SkillPersona, SlashMenuProps } from "./SlashMenu.js";

// Chronological transcript scroll model (2026-05-19 redesign):
// `useAutoScroll` is the FOLLOW / PAUSED / LOCKED state machine;
// `<JumpToLatestPill>` is the floating control cluster.
export {
  useAutoScroll,
  NEAR_BOTTOM_PX,
  RESUME_FOLLOW_PX,
} from "./use-auto-scroll.js";
export type {
  AutoScrollMode,
  UseAutoScrollOptions,
  UseAutoScrollResult,
} from "./use-auto-scroll.js";
export { JumpToLatestPill } from "./JumpToLatestPill.js";

// Tabular primitive — used inline in transcripts (kaos-md table
// auto-promotion) and standalone for `kaos-tabular` comparison
// grids. Lives under `/chat` for now because that's where its
// first consumers are; promote to `/data` if more rectangular
// surfaces want it.
export { DataTable } from "../data/DataTable.js";
export type {
  Column,
  ColumnKind,
  DataTableDensity,
  DataTableProps,
} from "../data/DataTable.js";
