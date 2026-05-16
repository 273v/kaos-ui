/**
 * `<SlashMenu>` — composer slash-command popover.
 *
 * Activates when the user types `/` as the FIRST non-whitespace
 * character of an otherwise empty composer. Shows a filterable list
 * of "skills" — named, reusable prompt templates the host loads from
 * its skills source (filesystem in dev, server-backed in production).
 *
 * Pattern: Claude Code Skills (`.claude/skills/<name>/SKILL.md`),
 * Linear Agent skills, LibreChat Presets. Each skill is the tuple
 * (name, description, prefill, optional persona, optional tool
 * groups, optional model).
 *
 * This component is presentational — the host owns the skills array
 * + the "did the user just hit /" detection + the prefill side effects
 * (composer value + persona / policy patches). Decoupled so a server-
 * loaded skill registry can swap in without touching the composer.
 */

import { useEffect, useId, useMemo, useRef, useState } from "react";

/**
 * Persona preset id. We keep this local to the package (matches the
 * server-side `Persona` Literal in kaos-agents 0.1.0a4) instead of
 * importing it, so the package stays decoupled from any app-level
 * type module. New persona ids land here when kaos-agents adds them.
 */
export type SkillPersona = "research" | "drafting" | "forensics";

export interface Skill {
  /** Stable id — the `/<id>` token typed in the composer. */
  id: string;
  /** Human-visible name shown in the menu. */
  name: string;
  /** One-line tagline used as menu subtext + tooltip. */
  description: string;
  /**
   * Prefill — the text the composer should hold after the user picks
   * this skill. Supports `{cursor}` to position the caret.
   */
  prefill: string;
  /** Optional persona preset to apply to the session. */
  persona?: SkillPersona;
  /** Optional model id to switch to. */
  model?: string;
  /**
   * Optional ceiling override — patch tool-set with these
   * `allowed_groups`. Useful for "Read-only research" skills that
   * lock the policy to documents+vfs.
   */
  allowed_groups?: string[];
}

export interface SlashMenuProps {
  /** All available skills. The host filters by org / workspace. */
  skills: Skill[];
  /** Filter string — typically `composerValue.slice(1)`. */
  query: string;
  /** Hide / show driven by the host (typing `/` on an empty composer). */
  open: boolean;
  /** Called when the user picks a skill. */
  onPick: (skill: Skill) => void;
  /** Called when the user dismisses (Esc, click outside, blur). */
  onClose: () => void;
}

export function SlashMenu({ skills, query, open, onPick, onClose }: SlashMenuProps) {
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return skills;
    return skills.filter(
      (s) =>
        s.id.toLowerCase().includes(q) ||
        s.name.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q),
    );
  }, [skills, query]);

  // Reset active item when the filtered set changes.
  useEffect(() => {
    setActive(0);
  }, [filtered.length]);

  // Keyboard navigation. We listen on `document` so the composer
  // textarea retains focus while the menu drives selection.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((i) => (filtered.length === 0 ? 0 : (i + 1) % filtered.length));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((i) =>
          filtered.length === 0 ? 0 : (i - 1 + filtered.length) % filtered.length,
        );
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        const picked = filtered[active];
        if (picked) {
          e.preventDefault();
          onPick(picked);
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, filtered, active, onPick, onClose]);

  if (!open) return null;

  return (
    <div
      ref={rootRef}
      role="listbox"
      id={listId}
      aria-label="Slash command skills"
      className="absolute bottom-full left-0 mb-2 w-80 max-h-72 overflow-y-auto rounded-lg border border-border bg-card shadow-md py-1 text-xs"
    >
      {filtered.length === 0 ? (
        <div className="px-3 py-3 italic text-foreground/55">
          No skills match {`"${query}"`}.
        </div>
      ) : (
        filtered.map((s, i) => (
          <button
            key={s.id}
            type="button"
            role="option"
            aria-selected={i === active}
            onMouseEnter={() => setActive(i)}
            // mousedown not click so the composer textarea doesn't
            // blur first (which would close us before our handler runs).
            onMouseDown={(e) => {
              e.preventDefault();
              onPick(s);
            }}
            className={[
              "w-full text-left px-3 py-2 flex items-start gap-2 transition-colors",
              i === active ? "bg-muted text-foreground" : "text-foreground/85 hover:bg-muted/60",
            ].join(" ")}
          >
            <span className="font-mono text-[11px] font-semibold text-accent shrink-0 mt-0.5">
              /{s.id}
            </span>
            <span className="flex-1 min-w-0">
              <span className="block font-medium">{s.name}</span>
              <span className="block mt-0.5 text-foreground/60 leading-snug">
                {s.description}
              </span>
              {(s.persona || s.allowed_groups) && (
                <span className="mt-1 flex flex-wrap gap-1 text-[10px] uppercase tracking-wide text-foreground/50">
                  {s.persona && (
                    <span className="rounded-full border border-border px-1.5 py-px">
                      {s.persona}
                    </span>
                  )}
                  {s.allowed_groups?.slice(0, 3).map((g) => (
                    <span key={g} className="rounded-full border border-border px-1.5 py-px">
                      {g}
                    </span>
                  ))}
                </span>
              )}
            </span>
          </button>
        ))
      )}
      <div className="border-t border-border/60 px-3 py-1.5 text-[10px] text-foreground/50 tabular-nums flex items-center justify-between">
        <span>↑↓ to navigate · ↵ to insert · esc to dismiss</span>
        <span>{filtered.length} skill{filtered.length === 1 ? "" : "s"}</span>
      </div>
    </div>
  );
}
