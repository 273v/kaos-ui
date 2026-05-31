// Chat surface — composer, message transcript, file upload UI,
// citations side panel, model picker.

export type {
  Column,
  ColumnKind,
  DataTableDensity,
  DataTableProps,
} from "../data/DataTable.js";
// Tabular primitive — used inline in transcripts (kaos-md table
// auto-promotion) and standalone for `kaos-tabular` comparison
// grids. Lives under `/chat` for now because that's where its
// first consumers are; promote to `/data` if more rectangular
// surfaces want it.
export { DataTable } from "../data/DataTable.js";
export type { CapabilityDecision } from "./CapabilityApproval.js";
export { CapabilityApproval } from "./CapabilityApproval.js";
export { CitationsPanel } from "./CitationsPanel.js";
export type { ComposerProps } from "./Composer.js";
export { Composer } from "./Composer.js";
export type { AskAboutSelection } from "./DocumentExplorer.js";
export { DocumentExplorer } from "./DocumentExplorer.js";
export { DropZone } from "./DropZone.js";
export { ElevationPill } from "./ElevationPill.js";
export { EmptyState } from "./EmptyState.js";
export { ErrorBanner } from "./ErrorBanner.js";
export { FileChips } from "./FileChips.js";
// AgenticLoop UI surface (kaos-agents 0.1.0a4):
export { GoalCheckBadge } from "./GoalCheckBadge.js";
export { JsonView } from "./JsonView.js";
export { JumpToLatestPill } from "./JumpToLatestPill.js";
export { LoopTerminatedBanner } from "./LoopTerminatedBanner.js";
export { Message } from "./Message.js";
export type { ModelEntry } from "./ModelPicker.js";
export { ModelPicker } from "./ModelPicker.js";
export { PlanCard } from "./PlanCard.js";
export { ReasoningSummary } from "./ReasoningSummary.js";
export { SkeletonLine, SkeletonRow } from "./Skeleton.js";
export type { Skill, SkillPersona, SlashMenuProps } from "./SlashMenu.js";
export { SlashMenu } from "./SlashMenu.js";
export { ToolCallBlock } from "./ToolCallBlock.js";
export { ToolPolicyBadge } from "./ToolPolicyBadge.js";
export { TurnStatus } from "./TurnStatus.js";
export type { FormattedToolCall, ResultKind } from "./tool-formatters.js";
export { formatToolCall, repairAndParseJson, toolLabel } from "./tool-formatters.js";
export { UsageChip } from "./UsageChip.js";
export type {
  AutoScrollMode,
  UseAutoScrollOptions,
  UseAutoScrollResult,
} from "./use-auto-scroll.js";
// Chronological transcript scroll model (2026-05-19 redesign):
// `useAutoScroll` is the FOLLOW / PAUSED / LOCKED state machine;
// `<JumpToLatestPill>` is the floating control cluster.
export {
  NEAR_BOTTOM_PX,
  RESUME_FOLLOW_PX,
  useAutoScroll,
} from "./use-auto-scroll.js";
export { VfsExplorer } from "./VfsExplorer.js";
