/**
 * EmptyState — shown when a chat thread has no messages yet.
 *
 * Layout: serif greeting H1, composer card just below it (so the user
 * can start typing immediately), then a 2-column starter grid.
 *
 * Modeled after Harvey's "Good morning, ⟨name⟩" hero. The greeting
 * picks one of three time-of-day variants from `Date.now()` so it
 * feels alive even without server-side personalization.
 */
import { Composer } from "@273v/kaos-ui-react/chat";
import { FileText, Gavel, type LucideIcon, Scale, Search } from "lucide-react";

import { StarterCard } from "@/components/chat/StarterCard";

interface EmptyStateProps {
  composerValue: string;
  onComposerChange: (value: string) => void;
  onSubmit: () => void;
  onSelectStarter: (prompt: string) => void;
  pending: boolean;
}

interface StarterDef {
  icon: LucideIcon;
  title: string;
  prompt: string;
}

/* Hard-coded for Phase A. Phase B reads `GET /v1/recipes` and maps
 * recipe names → starter cards with proper recipe injection. */
const STARTERS: StarterDef[] = [
  {
    icon: FileText,
    title: "Draft a memo",
    prompt:
      "Draft a short legal memo on the issue I describe. Ask me three clarifying questions first.",
  },
  {
    icon: Search,
    title: "Research a question",
    prompt:
      "Research the following legal question. Cite primary sources and flag anything you can't verify.",
  },
  {
    icon: Scale,
    title: "Review a contract",
    prompt:
      "Review the contract I'll attach for one-sided clauses, indemnities, and ambiguous definitions.",
  },
  {
    icon: Gavel,
    title: "Summarize a case",
    prompt:
      "Summarize the case I'll cite: facts, holding, reasoning, and key dicta. Note circuit and date.",
  },
];

function greetingFor(now: Date = new Date()): string {
  const h = now.getHours();
  if (h < 5) return "Good evening";
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export function EmptyState({
  composerValue,
  onComposerChange,
  onSubmit,
  onSelectStarter,
  pending,
}: EmptyStateProps) {
  const greeting = greetingFor();

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-8 px-6 pt-24 pb-12">
      <h1 className="font-display text-4xl text-foreground">{greeting}.</h1>

      <Composer
        value={composerValue}
        onChange={onComposerChange}
        onSubmit={onSubmit}
        pending={pending}
        placeholder="Ask anything, or pick a starting point below…"
      />

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {STARTERS.map((s) => (
          <StarterCard
            key={s.title}
            icon={s.icon}
            title={s.title}
            prompt={s.prompt}
            onSelect={onSelectStarter}
          />
        ))}
      </div>
    </div>
  );
}
