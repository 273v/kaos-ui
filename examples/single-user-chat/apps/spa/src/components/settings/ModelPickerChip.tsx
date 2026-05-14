// Inline composer chip that opens a model-picker popover.
// Click cycles through the catalog via a native <select> — clean and
// keyboard-accessible without a custom popover component.

import { ChevronDown } from "lucide-react";

import { useModels } from "@/hooks/use-models";

interface Props {
  value: string;
  onChange: (modelId: string) => void;
  disabled?: boolean;
}

export function ModelPickerChip({ value, onChange, disabled }: Props) {
  const models = useModels();
  const entries = models.data?.models ?? [];
  const current = entries.find((m) => m.id === value);

  return (
    <label
      className={
        "inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-border " +
        "bg-card hover:bg-muted transition-colors cursor-pointer relative " +
        (disabled ? "opacity-60 cursor-not-allowed" : "")
      }
      title="Model for the next turn"
    >
      <span className="font-medium">{current?.label ?? value}</span>
      <ChevronDown className="h-3 w-3 text-muted-foreground" />
      <select
        value={value}
        disabled={disabled || models.isLoading}
        onChange={(e) => onChange(e.target.value)}
        className="absolute inset-0 opacity-0 cursor-pointer"
        aria-label="Model"
      >
        {entries.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label}
          </option>
        ))}
      </select>
    </label>
  );
}
