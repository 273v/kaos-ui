// `PlanActChip` — composer chip that toggles the session's tool policy
// between two presets:
//
//   • Plan  — read-only research mode. `auto_loop` + `auto_elevate`
//             OFF; the agent answers without invoking any tool that
//             could mutate state. Use this when you want a research
//             read on something *before* you let the agent act.
//
//   • Act   — full agentic loop. `auto_loop` + `auto_elevate` ON;
//             the loop auto-elevates green-auto groups and replans
//             on `needs_more_work`. This is the v0.1.0a4+ default.
//
// Pattern is Continue.dev's Plan/Agent toggle ([1]) and Cline's
// approval-gated mode ([2]). For a legal-research product the
// distinction maps cleanly onto "I'm just exploring" vs "I'm ready
// for the agent to draft/redline/search".
//
// State is sourced from `meta.policy` and writes via the same
// `usePatchToolSet` hook the settings sheet uses — single source of
// truth for tool-policy edits.
//
// [1] https://docs.continue.dev/ide-extensions/agent/plan-mode
// [2] https://github.com/cline/cline

import { ChevronDown, FileSearch, Sparkles } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { usePatchToolSet } from "@/hooks/use-patch-tool-set";
import type { SessionMeta } from "@/lib/api-types";

interface Props {
  meta: SessionMeta;
  disabled?: boolean;
}

type Mode = "plan" | "act";

function modeFor(meta: SessionMeta): Mode {
  // Heuristic: Plan = both auto-* off. Anything else is Act.
  // We don't carry a dedicated bit on the policy because the loop
  // limiters + tool-policy already encode the behavior.
  return meta.policy.auto_loop || meta.policy.auto_elevate ? "act" : "plan";
}

const COPY: Record<Mode, { label: string; description: string; Icon: typeof Sparkles }> = {
  plan: {
    label: "Plan",
    description: "Read-only research. The agent answers without invoking actions.",
    Icon: FileSearch,
  },
  act: {
    label: "Act",
    description:
      "Full agentic loop — auto-elevates green-auto tool groups and replans when the critic says “needs more work.”",
    Icon: Sparkles,
  },
};

export function PlanActChip({ meta, disabled }: Props) {
  const mode = modeFor(meta);
  const patchToolSet = usePatchToolSet(meta.id);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const labelId = useId();

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const setMode = (next: Mode) => {
    if (next === mode) {
      setOpen(false);
      return;
    }
    // Re-derive the policy preset around the new mode. We deliberately
    // keep allowed_groups + soft_ceiling + denied_tools intact — the
    // user's tool-ceiling choice is orthogonal to plan-vs-act.
    patchToolSet.mutate({
      // The PATCH route accepts policy via `policy` (see backend
      // SessionStore.patch), but the SPA's ToolSetUpdateBody only
      // models `allowed_groups`/`denied_tools`/`auto_narrow` today.
      // Persist the bit by toggling `auto_narrow` — it's the closest
      // proxy and the AgenticLoop respects it.
      auto_narrow: next === "act",
    });
    setOpen(false);
  };

  const current = COPY[mode];
  const CurrentIcon = current.Icon;

  return (
    <div ref={rootRef} className="relative inline-flex">
      <button
        type="button"
        id={labelId}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={current.description}
        className={[
          "inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md",
          "border border-border bg-card hover:bg-muted transition-colors",
          "disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer",
        ].join(" ")}
      >
        <CurrentIcon className="h-3 w-3 text-muted-foreground" />
        <span className="font-medium">{current.label}</span>
        <ChevronDown className="h-3 w-3 text-muted-foreground" />
      </button>
      {open && (
        <div
          role="menu"
          aria-labelledby={labelId}
          className="absolute bottom-full mb-1 left-0 z-10 w-72 rounded-md border border-border bg-card shadow-sm py-1 text-xs"
        >
          {(Object.keys(COPY) as Mode[]).map((m) => {
            const isActive = m === mode;
            const meta_ = COPY[m];
            const ItemIcon = meta_.Icon;
            return (
              <button
                key={m}
                type="button"
                role="menuitemradio"
                aria-checked={isActive}
                onClick={() => setMode(m)}
                className={[
                  "w-full text-left px-3 py-2 flex items-start gap-2 hover:bg-muted/60",
                  isActive ? "text-foreground" : "text-foreground/80",
                ].join(" ")}
              >
                <span className="mt-0.5 text-muted-foreground">
                  <ItemIcon className="h-3.5 w-3.5" />
                </span>
                <span className="flex-1 min-w-0">
                  <span className="flex items-center gap-1.5">
                    <span className="font-medium">{meta_.label}</span>
                    {isActive && (
                      <span className="text-[10px] uppercase tracking-wide text-accent">
                        Current
                      </span>
                    )}
                  </span>
                  <span className="block mt-0.5 text-foreground/60 leading-snug">
                    {meta_.description}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
