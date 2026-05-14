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
  return (
    <ModelPicker
      value={value}
      models={entries}
      onChange={onChange}
      disabled={disabled || models.isLoading}
    />
  );
}
