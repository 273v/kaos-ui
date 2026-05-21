// App-specific wrapper that pulls the model list from /v1/models
// (via useModels) and renders the package's presentational <ModelPicker>.
// The package itself stays decoupled from how models are fetched.

import { ModelPicker } from "@273v/kaos-ui-react/chat";

import { useModels } from "@/hooks/use-models";

interface Props {
  value: string;
  onChange: (modelId: string) => void;
  disabled?: boolean;
}

export function ModelPickerChip({ value, onChange, disabled }: Props) {
  const models = useModels();
  const entries = models.data?.models ?? [];
  // #547 (0.1.1): render a skeleton-style chip while the model list is
  // loading. Pre-fix the chip rendered with every <option> disabled —
  // attorneys watching the first turn open saw a picker they couldn't
  // interact with for ~200ms and (per the v2 matrix report) interpreted
  // it as a bug. Loading and disabled are now separate concerns in the
  // a11y tree — the parent's `disabled` is honored normally, but the
  // model-list `isLoading` short-circuits to a non-interactive skeleton.
  if (models.isLoading) {
    return (
      <span
        role="status"
        aria-label="Loading models…"
        className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-border bg-muted/50 text-muted-foreground"
      >
        Loading models…
      </span>
    );
  }
  return <ModelPicker value={value} models={entries} onChange={onChange} disabled={disabled} />;
}
