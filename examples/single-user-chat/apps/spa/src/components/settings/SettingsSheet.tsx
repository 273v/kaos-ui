// Right-side sheet per UX-LANGUAGE.md § 4.7. Single scrollable column.
// Triggered from the chat header (or by a future keyboard shortcut).

import { Button } from "@kaos-chat-example/ui/components/ui/button";
import { Textarea } from "@kaos-chat-example/ui/components/ui/textarea";
import { X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useCategories } from "@/hooks/use-categories";
import { useModels } from "@/hooks/use-models";
import { usePatchMeta } from "@/hooks/use-patch-meta";
import { usePatchToolSet } from "@/hooks/use-patch-tool-set";
import type { SessionMeta } from "@/lib/api-types";

interface Props {
  open: boolean;
  onClose: () => void;
  meta: SessionMeta;
}

export function SettingsSheet({ open, onClose, meta }: Props) {
  const models = useModels();
  const categories = useCategories();
  const patch = usePatchMeta(meta.id);
  const patchToolSet = usePatchToolSet(meta.id);

  // Local edit buffer — only commits to the server on Save.
  const [title, setTitle] = useState(meta.title);
  const [model, setModel] = useState(meta.model);
  const [systemPrompt, setSystemPrompt] = useState(meta.system_prompt);
  // TR-8: tool policy edit buffer. Tracks the ceiling (set of group
  // ids the user wants enabled) + auto_narrow toggle. The bool
  // tools_enabled view is derived from `allowedGroups.length > 0`.
  const [allowedGroups, setAllowedGroups] = useState<string[]>(
    meta.tool_set?.allowed_groups ?? [],
  );
  const [autoNarrow, setAutoNarrow] = useState<boolean>(meta.tool_set?.auto_narrow ?? true);

  useEffect(() => {
    if (open) {
      setTitle(meta.title);
      setModel(meta.model);
      setSystemPrompt(meta.system_prompt);
      setAllowedGroups(meta.tool_set?.allowed_groups ?? []);
      setAutoNarrow(meta.tool_set?.auto_narrow ?? true);
    }
  }, [open, meta]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && open) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const sheetRef = useRef<HTMLElement | null>(null);

  // Trap focus inside the sheet while open. Tab cycles within; on close
  // we restore focus to the trigger (the calling code keeps a ref).
  useEffect(() => {
    if (!open) return;
    const sheet = sheetRef.current;
    if (!sheet) return;
    // Move initial focus into the dialog so screen readers announce it.
    const firstFocusable = sheet.querySelector<HTMLElement>(
      'input, textarea, select, button, [tabindex]:not([tabindex="-1"])',
    );
    firstFocusable?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const focusables = sheet.querySelectorAll<HTMLElement>(
        'input, textarea, select, button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (!first || !last) return;
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;

  const onSave = async () => {
    // Two independent PATCHes. Tool policy lives on a separate route
    // so an unknown-group validation error doesn't roll back legitimate
    // edits to title / model / prompt.
    await patch.mutateAsync({
      title,
      model,
      system_prompt: systemPrompt,
    });
    await patchToolSet.mutateAsync({
      allowed_groups: allowedGroups,
      auto_narrow: autoNarrow,
    });
    onClose();
  };

  // Preset shortcuts. Picking a preset writes to allowedGroups; the
  // grid reflects. "Custom" emerges automatically when the grid
  // doesn't match any preset.
  const PRESETS: { id: string; label: string; groups: string[] }[] = useMemo(
    () => [
      { id: "none", label: "None", groups: [] },
      { id: "docs", label: "Documents only", groups: ["documents", "citations", "vfs"] },
      {
        id: "docs+web",
        label: "Documents + web",
        groups: ["documents", "citations", "vfs", "web"],
      },
      {
        id: "all",
        label: "All read-only",
        groups: (categories.data?.categories ?? []).map((c) => c.id),
      },
    ],
    [categories.data],
  );

  const activePreset = useMemo(() => {
    const sorted = [...allowedGroups].sort().join(",");
    for (const p of PRESETS) {
      if ([...p.groups].sort().join(",") === sorted) return p.id;
    }
    return "custom";
  }, [allowedGroups, PRESETS]);

  return (
    <>
      <div className="fixed inset-0 z-40 bg-foreground/10" onClick={onClose} aria-hidden />
      <aside
        ref={sheetRef}
        className="fixed inset-y-0 right-0 z-50 w-full max-w-md bg-background border-l border-border shadow-none overflow-y-auto"
        role="dialog"
        aria-modal="true"
        aria-label="Session settings"
      >
        <header className="flex items-center justify-between px-5 py-4 border-b border-border sticky top-0 bg-background">
          <h2 className="text-base font-medium">Session settings</h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded hover:bg-muted text-muted-foreground"
            aria-label="Close settings"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="p-5 space-y-6">
          <Field label="Title">
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full h-9 px-3 rounded-md border border-input bg-background text-sm"
            />
          </Field>

          <Field label="Model" hint="Applies to the next turn.">
            <select
              value={model}
              disabled={models.isLoading}
              onChange={(e) => setModel(e.target.value)}
              className="w-full h-9 px-2 rounded-md border border-input bg-background text-sm"
            >
              {(models.data?.models ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </Field>

          <Field
            label="System prompt"
            hint="Instructions threaded as `instructions` on every turn."
          >
            <Textarea
              rows={6}
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              className="resize-y"
            />
          </Field>

          <Field
            label="Tool policy"
            hint="Which tool categories the agent may use, and how aggressively to narrow per turn."
          >
            <div className="space-y-3">
              {/* Preset picker — clicking writes to allowedGroups. */}
              <div>
                <label
                  htmlFor="tool-preset"
                  className="block text-[11px] text-muted-foreground mb-1"
                >
                  Preset
                </label>
                <select
                  id="tool-preset"
                  className="w-full text-sm bg-background border border-input rounded-md px-2 py-1.5"
                  value={activePreset}
                  onChange={(e) => {
                    const preset = PRESETS.find((p) => p.id === e.target.value);
                    if (preset) setAllowedGroups(preset.groups);
                    // "custom" is a derived state — pick any other
                    // preset to leave it. Selecting "custom" itself
                    // is a no-op (the grid below is the authority).
                  }}
                >
                  {PRESETS.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                  {activePreset === "custom" && <option value="custom">Custom</option>}
                </select>
              </div>

              {/* Per-category checkboxes — the source of truth. */}
              {categories.isPending && (
                <p className="text-xs text-muted-foreground italic">Loading categories…</p>
              )}
              {categories.isError && (
                <p className="text-xs text-destructive">
                  Failed to load tool categories. The toggle is unavailable.
                </p>
              )}
              {categories.data && (
                <ul className="space-y-1.5">
                  {categories.data.categories.map((cat) => {
                    const checked = allowedGroups.includes(cat.id);
                    return (
                      <li key={cat.id}>
                        <label className="flex items-start gap-2 text-sm cursor-pointer">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) =>
                              setAllowedGroups((groups) =>
                                e.target.checked
                                  ? Array.from(new Set([...groups, cat.id]))
                                  : groups.filter((g) => g !== cat.id),
                              )
                            }
                            className="mt-0.5 h-4 w-4 shrink-0"
                          />
                          <span className="flex-1">
                            <span className="font-medium">{cat.label}</span>
                            <span className="text-muted-foreground">
                              {" "}
                              · {cat.tool_count} tool{cat.tool_count === 1 ? "" : "s"}
                            </span>
                            <span className="block text-[11px] text-muted-foreground leading-snug">
                              {cat.description}
                            </span>
                          </span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              )}

              {/* Auto-narrow toggle. */}
              <label className="flex items-start gap-2 text-sm cursor-pointer border-t border-border pt-3">
                <input
                  type="checkbox"
                  checked={autoNarrow}
                  onChange={(e) => setAutoNarrow(e.target.checked)}
                  className="mt-0.5 h-4 w-4 shrink-0"
                />
                <span className="flex-1">
                  <span className="font-medium">Auto-narrow tools per turn</span>
                  <span className="block text-[11px] text-muted-foreground leading-snug">
                    Runs a small Haiku planner before each turn that picks the
                    smallest set of categories within your ceiling. Falls back to
                    the full ceiling when uncertain — narrowing is never a
                    security gate.
                  </span>
                </span>
              </label>
            </div>
          </Field>

          {(patch.isError || patchToolSet.isError) && (
            <div className="text-sm text-destructive border border-destructive/30 rounded-md px-3 py-2">
              {patch.error instanceof Error
                ? patch.error.message
                : patchToolSet.error instanceof Error
                  ? patchToolSet.error.message
                  : "Save failed."}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2 border-t border-border">
            <Button variant="ghost" onClick={onClose} disabled={patch.isPending}>
              Cancel
            </Button>
            <Button onClick={onSave} disabled={patch.isPending}>
              {patch.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
      </aside>
    </>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="text-xs font-medium">{label}</span>
        {hint && <span className="text-[11px] text-muted-foreground">{hint}</span>}
      </div>
      {children}
    </div>
  );
}
