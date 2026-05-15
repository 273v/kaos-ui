/**
 * <SettingsSheet> Tool policy section — pins TR-8 / TR-12.
 *
 * Validates:
 *  - Categories from GET /v1/chat/categories render as checkboxes.
 *  - Toggling a category flips the local state.
 *  - Preset picker writes through to the grid.
 *  - "Custom" preset emerges automatically when grid doesn't match.
 *
 * We mock the fetch + categories hook rather than spinning a real
 * backend; that's covered in the integration tests (TR-11).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsSheet } from "@/components/settings/SettingsSheet";
import type { SessionMeta } from "@/lib/api-types";

function makeMeta(overrides: Partial<SessionMeta> = {}): SessionMeta {
  return {
    id: "01J123",
    title: "T",
    model: "anthropic:claude-haiku-4-5",
    system_prompt: "Be helpful.",
    tools_enabled: true,
    tool_set: {
      allowed_groups: ["documents", "citations", "vfs"],
      denied_tools: [],
      auto_narrow: true,
    },
    created_at: new Date().toISOString(),
    last_message_at: null,
    message_count: 0,
    archived: false,
    starred: false,
    title_source: "auto",
    ...overrides,
  };
}

const CATEGORIES_RESPONSE = {
  categories: [
    {
      id: "citations",
      label: "Citations",
      description: "Extract typed citations.",
      default_enabled: true,
      tool_count: 3,
    },
    {
      id: "documents",
      label: "Documents",
      description: "Parse uploaded PDF/DOCX/PPTX.",
      default_enabled: true,
      tool_count: 27,
    },
    {
      id: "vfs",
      label: "File browser",
      description: "Browse the session VFS.",
      default_enabled: true,
      tool_count: 5,
    },
    {
      id: "web",
      label: "Web sources",
      description: "Live web access.",
      default_enabled: false,
      tool_count: 30,
    },
  ],
};

const MODELS_RESPONSE = {
  models: [
    {
      id: "anthropic:claude-haiku-4-5",
      label: "Haiku 4.5",
      provider: "anthropic" as const,
    },
  ],
};

function renderSheet(meta = makeMeta()) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <SettingsSheet open={true} onClose={() => {}} meta={meta} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockImplementation((url) => {
    const u = typeof url === "string" ? url : url.toString();
    if (u.includes("/v1/chat/categories")) {
      return Promise.resolve(
        new Response(JSON.stringify(CATEGORIES_RESPONSE), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    if (u.includes("/v1/models")) {
      return Promise.resolve(
        new Response(JSON.stringify(MODELS_RESPONSE), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    return Promise.resolve(new Response("{}", { status: 200 }));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("<SettingsSheet> Tool policy section", () => {
  it("renders one checkbox per category once GET /categories resolves", async () => {
    renderSheet();
    expect(await screen.findByText("Documents")).toBeInTheDocument();
    expect(screen.getByText("Citations")).toBeInTheDocument();
    expect(screen.getByText("File browser")).toBeInTheDocument();
    expect(screen.getByText("Web sources")).toBeInTheDocument();
  });

  it("marks the session's allowed_groups as checked", async () => {
    renderSheet();
    await screen.findByText("Documents");
    // Documents is in default ceiling -> checked.
    const docsRow = screen.getByText("Documents").closest("label");
    const docsCheckbox = docsRow?.querySelector("input[type=checkbox]");
    expect((docsCheckbox as HTMLInputElement)?.checked).toBe(true);

    // Web is NOT in default ceiling -> unchecked.
    const webRow = screen.getByText("Web sources").closest("label");
    const webCheckbox = webRow?.querySelector("input[type=checkbox]");
    expect((webCheckbox as HTMLInputElement)?.checked).toBe(false);
  });

  it("toggles a category checkbox locally", async () => {
    renderSheet();
    await screen.findByText("Web sources");
    const webRow = screen.getByText("Web sources").closest("label");
    const webCheckbox = webRow?.querySelector("input[type=checkbox]") as HTMLInputElement;
    expect(webCheckbox.checked).toBe(false);

    fireEvent.click(webCheckbox);
    expect(webCheckbox.checked).toBe(true);
  });

  it("preset picker writes through to the grid", async () => {
    renderSheet();
    await screen.findByText("Documents");
    const preset = screen.getByLabelText("Preset") as HTMLSelectElement;

    fireEvent.change(preset, { target: { value: "docs+web" } });
    await waitFor(() => {
      const webRow = screen.getByText("Web sources").closest("label");
      const webCheckbox = webRow?.querySelector("input[type=checkbox]") as HTMLInputElement;
      expect(webCheckbox.checked).toBe(true);
    });
  });

  it("preset reflects the default ceiling on initial render", async () => {
    renderSheet();
    await screen.findByText("Documents");
    const preset = screen.getByLabelText("Preset") as HTMLSelectElement;
    expect(preset.value).toBe("docs"); // docs / citations / vfs
  });

  it("preset switches to Custom when the grid doesn't match any preset", async () => {
    renderSheet(
      makeMeta({
        tool_set: {
          // unique combination — not in any preset
          allowed_groups: ["documents", "web"],
          denied_tools: [],
          auto_narrow: true,
        },
      }),
    );
    await screen.findByText("Documents");
    const preset = screen.getByLabelText("Preset") as HTMLSelectElement;
    expect(preset.value).toBe("custom");
  });

  it("auto-narrow toggle reflects + flips local state", async () => {
    renderSheet();
    await screen.findByText("Auto-narrow tools per turn");
    const toggleLabel = screen.getByText("Auto-narrow tools per turn").closest("label");
    const checkbox = toggleLabel?.querySelector("input[type=checkbox]") as HTMLInputElement;
    expect(checkbox.checked).toBe(true);

    fireEvent.click(checkbox);
    expect(checkbox.checked).toBe(false);
  });
});
