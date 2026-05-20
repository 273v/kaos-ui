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
  const [allowedGroups, setAllowedGroups] = useState<string[]>(meta.tool_set?.allowed_groups ?? []);
  const [autoNarrow, setAutoNarrow] = useState<boolean>(meta.tool_set?.auto_narrow ?? true);
  // M.6 — three new AgenticLoop toggles. Pulled from the canonical
  // `meta.policy` shape; the legacy `meta.tool_set` only carries
  // allowed_groups/denied_tools/auto_narrow.
  const [autoElevate, setAutoElevate] = useState<boolean>(meta.policy?.auto_elevate ?? true);
  const [autoLoop, setAutoLoop] = useState<boolean>(meta.policy?.auto_loop ?? true);
  const [persona, setPersona] = useState<"research" | "drafting" | "forensics">(
    meta.policy?.persona ?? "research",
  );
  // #312 U.10 — three AgenticLoop budget caps. Backend (SessionPolicyWire)
  // exposes these with hard bounds:
  //   max_loop_iterations: int 1–10 (default 3)
  //   max_loop_cost_usd:    float 0–10 (default 0.25)
  //   max_loop_wall_clock_seconds: float 0–600 (default 60)
  // We store as strings to support empty-input transient states and
  // coerce on submit.
  const [maxIterations, setMaxIterations] = useState<string>(
    String(meta.policy?.max_loop_iterations ?? 3),
  );
  const [maxCostUsd, setMaxCostUsd] = useState<string>(
    String(meta.policy?.max_loop_cost_usd ?? 0.25),
  );
  const [maxWallSeconds, setMaxWallSeconds] = useState<string>(
    String(meta.policy?.max_loop_wall_clock_seconds ?? 60),
  );

  useEffect(() => {
    if (open) {
      setTitle(meta.title);
      setModel(meta.model);
      setSystemPrompt(meta.system_prompt);
      setAllowedGroups(meta.tool_set?.allowed_groups ?? []);
      setAutoNarrow(meta.tool_set?.auto_narrow ?? true);
      setAutoElevate(meta.policy?.auto_elevate ?? true);
      setAutoLoop(meta.policy?.auto_loop ?? true);
      setPersona(meta.policy?.persona ?? "research");
      setMaxIterations(String(meta.policy?.max_loop_iterations ?? 3));
      setMaxCostUsd(String(meta.policy?.max_loop_cost_usd ?? 0.25));
      setMaxWallSeconds(String(meta.policy?.max_loop_wall_clock_seconds ?? 60));
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

  // Preset shortcuts. Picking a preset writes to allowedGroups; the
  // grid reflects. "Custom" emerges automatically when the grid
  // doesn't match any preset.
  //
  // NOTE: these two useMemo calls MUST run on every render, regardless
  // of `open`, because the previous early-return below them caused the
  // hook order to change between closed → open transitions ("Rendered
  // more hooks than during the previous render"). Keep the early
  // return BELOW all hook calls.
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

  if (!open) return null;

  const onSave = async () => {
    // Two independent PATCHes. Tool policy lives on a separate route
    // so an unknown-group validation error doesn't roll back legitimate
    // edits to title / model / prompt.
    //
    // We intersect ``allowedGroups`` with the runtime-registered category
    // IDs (from ``/v1/chat/categories``) before sending. Without that,
    // the persona soft-ceiling can leak phantom group names like
    // ``browser`` / ``forensics`` / ``netinfra`` / ``retrieval`` into
    // ``allowed_groups`` — those groups aren't registered on this
    // runtime, the backend 422s, and the user sees a generic
    // "Save failed." with no way to recover.
    const registeredGroupIds = new Set((categories.data?.categories ?? []).map((c) => c.id));
    const filteredAllowedGroups = registeredGroupIds.size
      ? allowedGroups.filter((g) => registeredGroupIds.has(g))
      : allowedGroups;

    // Wrap both mutations so React-Query surfaces the error via
    // ``patch.error`` / ``patchToolSet.error`` and the inline
    // ``ApiError.message`` block below shows the server's ``what``
    // detail — but the outer promise resolves so the click handler
    // doesn't log ``Uncaught (in promise)``.
    try {
      await patch.mutateAsync({
        title,
        model,
        system_prompt: systemPrompt,
      });
      // #312: coerce + clamp budget strings to the backend's documented
      // bounds. Empty / non-numeric falls back to the current value or
      // the documented default to avoid sending NaN.
      const iters = Math.max(
        1,
        Math.min(10, Number.parseInt(maxIterations, 10) || (meta.policy?.max_loop_iterations ?? 3)),
      );
      const cost = Math.max(
        0.01,
        Math.min(
          10,
          Number.parseFloat(maxCostUsd) || (meta.policy?.max_loop_cost_usd ?? 0.25),
        ),
      );
      const wall = Math.max(
        1,
        Math.min(
          600,
          Number.parseFloat(maxWallSeconds) ||
            (meta.policy?.max_loop_wall_clock_seconds ?? 60),
        ),
      );
      await patchToolSet.mutateAsync({
        allowed_groups: filteredAllowedGroups,
        auto_narrow: autoNarrow,
        auto_elevate: autoElevate,
        auto_loop: autoLoop,
        persona,
        max_loop_iterations: iters,
        max_loop_cost_usd: cost,
        max_loop_wall_clock_seconds: wall,
      });
      onClose();
    } catch {
      // Already exposed via ``patch.error`` / ``patchToolSet.error``.
      // The dialog stays open so the user can fix and retry.
    }
  };

  return (
    <>
      {/*
        Backdrop click-to-dismiss. A `<button>` (not `<div>`) so
        keyboard users can Tab to it and press Enter / Space to
        dismiss. `aria-label` matches the sheet's `aria-label` so a
        screen reader reads "Close session settings" when the user
        lands on the backdrop. Visually it's the same translucent
        scrim — `appearance-none + cursor-default + focus-visible`
        keeps it from looking like a button.
      */}
      <button
        type="button"
        aria-label="Close session settings"
        onClick={onClose}
        className="fixed inset-0 z-40 bg-foreground/10 cursor-default focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
      />
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
                    Runs a small Haiku planner before each turn that picks the smallest set of
                    categories within your ceiling. Falls back to the full ceiling when uncertain —
                    narrowing is never a security gate.
                  </span>
                </span>
              </label>

              {/* M.6 — Auto-elevate. */}
              <label className="flex items-start gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoElevate}
                  onChange={(e) => setAutoElevate(e.target.checked)}
                  className="mt-0.5 h-4 w-4 shrink-0"
                />
                <span className="flex-1">
                  <span className="font-medium">Auto-elevate green-auto groups</span>
                  <span className="block text-[11px] text-muted-foreground leading-snug">
                    When the per-turn planner reports a tool group the agent wants but the ceiling
                    doesn't include, silently widen the ceiling up to the soft ceiling. Off = the
                    loop runs with only the current allowed groups.
                  </span>
                </span>
              </label>

              {/* M.6 — Auto-loop. */}
              <label className="flex items-start gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoLoop}
                  onChange={(e) => setAutoLoop(e.target.checked)}
                  className="mt-0.5 h-4 w-4 shrink-0"
                />
                <span className="flex-1">
                  <span className="font-medium">Multi-iteration agentic loop</span>
                  <span className="block text-[11px] text-muted-foreground leading-snug">
                    Re-plan and re-execute when the critic says the answer needs more work. Off =
                    one ReAct pass per turn, no self-correction.
                  </span>
                </span>
              </label>

              {/* #312 — AgenticLoop budget caps. Three-column grid: each
                  field gets its own label + numeric input + caption.
                  Disabled when auto_loop is OFF since the caps only
                  apply to the multi-iteration path. */}
              <fieldset className="border-t border-border pt-3" disabled={!autoLoop}>
                <legend className="text-[11px] uppercase tracking-wider text-muted-foreground mb-2">
                  Loop budgets
                </legend>
                <div className={`grid grid-cols-3 gap-3 ${!autoLoop ? "opacity-60" : ""}`}>
                  <div>
                    <label
                      htmlFor="max-loop-iterations"
                      className="block text-[11px] text-muted-foreground mb-1"
                    >
                      Max iterations
                    </label>
                    <input
                      id="max-loop-iterations"
                      type="number"
                      min={1}
                      max={10}
                      step={1}
                      value={maxIterations}
                      onChange={(e) => setMaxIterations(e.target.value)}
                      className="w-full text-sm bg-background border border-input rounded-md px-2 py-1.5 tabular-nums"
                    />
                    <p className="mt-1 text-[10px] text-muted-foreground">1–10 (default 3)</p>
                  </div>
                  <div>
                    <label
                      htmlFor="max-loop-cost"
                      className="block text-[11px] text-muted-foreground mb-1"
                    >
                      Max cost (USD)
                    </label>
                    <input
                      id="max-loop-cost"
                      type="number"
                      min={0.01}
                      max={10}
                      step={0.05}
                      value={maxCostUsd}
                      onChange={(e) => setMaxCostUsd(e.target.value)}
                      className="w-full text-sm bg-background border border-input rounded-md px-2 py-1.5 tabular-nums"
                    />
                    <p className="mt-1 text-[10px] text-muted-foreground">$0.01–$10 (default $0.25)</p>
                  </div>
                  <div>
                    <label
                      htmlFor="max-loop-wall"
                      className="block text-[11px] text-muted-foreground mb-1"
                    >
                      Max wall-clock (s)
                    </label>
                    <input
                      id="max-loop-wall"
                      type="number"
                      min={1}
                      max={600}
                      step={5}
                      value={maxWallSeconds}
                      onChange={(e) => setMaxWallSeconds(e.target.value)}
                      className="w-full text-sm bg-background border border-input rounded-md px-2 py-1.5 tabular-nums"
                    />
                    <p className="mt-1 text-[10px] text-muted-foreground">1–600s (default 60)</p>
                  </div>
                </div>
                <p className="mt-2 text-[11px] text-muted-foreground leading-snug">
                  Three independent hard caps. The loop terminates when ANY cap fires — usually
                  the cost cap. Defense-in-depth against runaway iterations.
                </p>
              </fieldset>

              {/* M.6 — Persona picker. */}
              <div className="border-t border-border pt-3">
                <label
                  htmlFor="persona-picker"
                  className="block text-[11px] text-muted-foreground mb-1"
                >
                  Persona
                </label>
                <select
                  id="persona-picker"
                  className="w-full text-sm bg-background border border-input rounded-md px-2 py-1.5"
                  value={persona}
                  onChange={(e) =>
                    setPersona(e.target.value as "research" | "drafting" | "forensics")
                  }
                >
                  <option value="research">Research</option>
                  <option value="drafting">Drafting</option>
                  <option value="forensics">Forensics</option>
                </select>
                <p className="mt-1 text-[11px] text-muted-foreground leading-snug">
                  Threaded into the per-turn planner as session intent. Changing this here does NOT
                  rewrite your tool ceiling — use the persona chips on the welcome page for a full
                  preset swap.
                </p>
              </div>
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
            <Button
              variant="ghost"
              onClick={onClose}
              disabled={patch.isPending || patchToolSet.isPending}
            >
              Cancel
            </Button>
            <Button onClick={onSave} disabled={patch.isPending || patchToolSet.isPending}>
              {patch.isPending || patchToolSet.isPending ? "Saving…" : "Save"}
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
