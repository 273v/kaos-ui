/**
 * <ModelPickerChip> #547 — loading skeleton instead of disabled-picker flash.
 *
 * Pre-0.1.1 the chip rendered `<select>` with `disabled={disabled ||
 * models.isLoading}` so on a fresh visit the first ~200ms showed a
 * picker every attorney saw as broken. 0.1.1 short-circuits to a
 * non-interactive "Loading models…" skeleton while the model list is
 * loading and only renders the real `<select>` once data has resolved.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ModelPickerChip } from "@/components/settings/ModelPickerChip";

// Mock the data hook so we control isLoading + data shape without an
// HTTP layer. Returning shape mirrors `useModels()` at
// `src/hooks/use-models.ts`.
vi.mock("@/hooks/use-models", () => ({
  useModels: vi.fn(),
}));

const { useModels } = await import("@/hooks/use-models");

describe("<ModelPickerChip>", () => {
  it("renders a loading skeleton while models are loading", () => {
    vi.mocked(useModels).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as ReturnType<typeof useModels>);

    render(<ModelPickerChip value="anthropic:claude-haiku-4-5" onChange={() => {}} />);

    expect(screen.getByLabelText("Loading models…")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("renders the real picker once models have loaded", () => {
    vi.mocked(useModels).mockReturnValue({
      data: {
        models: [
          {
            id: "anthropic:claude-haiku-4-5",
            label: "Claude Haiku 4.5",
            provider: "anthropic",
            is_default: true,
          },
          {
            id: "openai:gpt-5.4-mini",
            label: "GPT-5.4 mini",
            provider: "openai",
            is_default: false,
          },
        ],
      },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useModels>);

    const onChange = vi.fn();
    render(<ModelPickerChip value="anthropic:claude-haiku-4-5" onChange={onChange} />);

    const combobox = screen.getByRole("combobox");
    expect(combobox).toBeInTheDocument();
    expect(combobox).not.toBeDisabled();
    // The skeleton MUST be gone — pre-fix shape would have it sit alongside
    // a disabled combobox.
    expect(screen.queryByLabelText("Loading models…")).not.toBeInTheDocument();
  });

  it("honors the parent's disabled prop without conflating it with isLoading", () => {
    vi.mocked(useModels).mockReturnValue({
      data: {
        models: [
          {
            id: "anthropic:claude-haiku-4-5",
            label: "Claude Haiku 4.5",
            provider: "anthropic",
            is_default: true,
          },
        ],
      },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useModels>);

    render(<ModelPickerChip value="anthropic:claude-haiku-4-5" onChange={() => {}} disabled />);

    expect(screen.getByRole("combobox")).toBeDisabled();
  });
});
