/**
 * Inline composer chip that opens a model-picker popover via a native
 * `<select>` — keyboard-accessible without a custom popover component.
 *
 * Fully presentational — the host owns `models`. The kaos-agents
 * example backend exposes `GET /v1/models`; consumers can use
 * `transportJson<{models: ModelEntry[]}>` to fetch + cache it
 * themselves.
 */

import { ChevronDown } from "lucide-react";

export interface ModelEntry {
  /** Provider-prefixed id, e.g. `anthropic:claude-opus-4-7`. */
  id: string;
  /** Human label shown in the picker. */
  label: string;
  /** Optional provider for logo / coloring. */
  provider?: string;
  /** Optional hint shown next to the label. */
  recommended_for?: string | null;
}

interface Props {
  value: string;
  models: readonly ModelEntry[];
  onChange: (modelId: string) => void;
  disabled?: boolean;
  /** Hover/title text. */
  title?: string;
}

export function ModelPicker({
  value,
  models,
  onChange,
  disabled,
  title = "Model for the next turn",
}: Props) {
  const current = models.find((m) => m.id === value);

  return (
    <label
      className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-border bg-card hover:bg-muted transition-colors cursor-pointer relative ${disabled ? "opacity-60 cursor-not-allowed" : ""}`}
      title={title}
    >
      <span className="font-medium">{current?.label ?? value}</span>
      <ChevronDown className="h-3 w-3 text-muted-foreground" />
      <select
        id="composer-model"
        name="composer-model"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="absolute inset-0 opacity-0 cursor-pointer"
        aria-label="Model"
      >
        {models.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label}
          </option>
        ))}
      </select>
    </label>
  );
}
