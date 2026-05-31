// `/sessions` index — the empty-state landing when no session is selected.
//
// Per AUDIT.md §2 W1 + W2 + RESEARCH-sota.md §6 ("4-card capability
// grid is the dominant pattern"): replace the bare "Welcome." heading
// with a 4-card grid that prefills the composer of a freshly-created
// session. Each card answers "what should the user do now?" with a
// one-click prefill (not a topic prompt — a *capability* prompt).
//
// Persona chips (M.7) live below the grid as a quieter row — picking
// one creates the session with that policy preset rather than the
// research-persona default.

import { useMutation } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { FileSearch, GavelIcon, Globe, PenLine } from "lucide-react";

import { useCreateSession } from "@/hooks/use-create-session";
import { apiJson } from "@/lib/api-fetch";
import type { Persona, SessionMeta } from "@/lib/api-types";

export const Route = createFileRoute("/_auth/sessions/")({
  component: SessionsEmpty,
});

// Capability cards — each one prefills the composer of a newly-created
// session, NOT a topic prompt. The user picks the *shape of the task*
// they want help with; the agent figures out the specifics.
//
// Ordered by frequency for a legal-research target user (research /
// drafting / forensics personas); icons are deliberately not legal-
// specific to keep the template re-usable across domains.
const CAPABILITY_CARDS: ReadonlyArray<{
  id: string;
  label: string;
  description: string;
  prompt: string;
  Icon: typeof PenLine;
}> = [
  {
    id: "search-fr",
    label: "Search the Federal Register",
    description: "Find a recent rule or notice with citations.",
    prompt:
      "Search the Federal Register for the most recent rule about dairy product labeling. Give me the publication date and the issuing agency, with the FR document number.",
    Icon: Globe,
  },
  {
    id: "summarize-doc",
    label: "Summarize an uploaded document",
    description: "Drop a PDF / DOCX / PPTX and ask for a structured summary.",
    prompt:
      "Summarize the document I just uploaded. Structure the output as: parties, governing law, key obligations, termination, and unusual clauses.",
    Icon: FileSearch,
  },
  {
    id: "draft-redline",
    label: "Draft or redline",
    description: "Author a clause, memo, or response with citations.",
    prompt:
      "Draft a short memo on the implications of FTC's recent non-compete rule for an existing senior-executive non-compete clause.",
    Icon: PenLine,
  },
  {
    id: "verify-claim",
    label: "Verify a citation or claim",
    description: "Pull the source text and check what's actually said.",
    prompt:
      "Find 7 C.F.R. § 1000.40 in the eCFR and quote the part that defines 'producer-handler.'",
    Icon: GavelIcon,
  },
];

const PERSONA_CHIPS: ReadonlyArray<{
  id: Persona;
  label: string;
  description: string;
}> = [
  {
    id: "research",
    label: "Research",
    description: "Web + documents + retrieval (the 80% default).",
  },
  {
    id: "drafting",
    label: "Drafting",
    description: "Research plus authoring tools (DOCX / PPTX / XLSX).",
  },
  {
    id: "forensics",
    label: "Forensics",
    description: "Tight ceiling — local files only, no web egress.",
  },
];

function SessionsEmpty() {
  const navigate = useNavigate();
  const createSession = useCreateSession();

  // For persona chips we POST + PATCH the tool-set in one shot. The
  // back-end accepts policy on PATCH (`patch_tool_set` → SessionStore.patch
  // → SessionPolicyWire.for_persona). We don't have a hook for that
  // exact combo, so inline a small mutation.
  const createWithPersona = useMutation({
    mutationFn: async (persona: Persona) => {
      const session = await createSession.mutateAsync({});
      // The session creates with the research-persona default.
      // For drafting/forensics, immediately PATCH the policy.
      if (persona !== "research") {
        await apiJson<SessionMeta>(`/v1/chat/sessions/${encodeURIComponent(session.id)}/tool-set`, {
          method: "PATCH",
          body: JSON.stringify({ persona }),
        });
      }
      return session;
    },
    onSuccess: (session) => {
      navigate({
        to: "/sessions/$id",
        params: { id: session.id },
      });
    },
  });

  const startWith = (prompt: string) => {
    // Create a fresh session + drop the user on it with the prompt
    // pre-filled. Vite query-state passes the prefill via `?prefill=`
    // so the chat route picks it up on mount.
    createSession.mutate(
      {},
      {
        onSuccess: (session) => {
          navigate({
            to: "/sessions/$id",
            params: { id: session.id },
            search: { prefill: prompt },
          });
        },
      },
    );
  };

  const busy = createSession.isPending || createWithPersona.isPending;

  return (
    <div className="min-h-full flex items-center justify-center px-6 py-12">
      <div className="w-full max-w-3xl">
        <header className="text-center mb-10">
          <h1 className="text-4xl font-serif font-light mb-2">What can I help with?</h1>
          <p className="text-sm text-muted-foreground">
            Start a conversation below — or press{" "}
            <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] font-mono">
              ⌘K
            </kbd>{" "}
            for a blank chat.
          </p>
        </header>

        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-10 list-none p-0 m-0">
          {CAPABILITY_CARDS.map((card) => (
            <li key={card.id}>
              <button
                type="button"
                disabled={busy}
                onClick={() => startWith(card.prompt)}
                className="group w-full h-full text-left rounded-lg border border-border bg-card hover:bg-muted/40 hover:border-accent/40 transition-colors px-4 py-3.5 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <div className="flex items-start gap-2.5">
                  <span className="mt-0.5 text-muted-foreground group-hover:text-accent transition-colors">
                    <card.Icon className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-sm leading-tight mb-1">{card.label}</p>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      {card.description}
                    </p>
                  </div>
                </div>
              </button>
            </li>
          ))}
        </ul>

        <div className="flex flex-wrap items-center justify-center gap-2 text-xs">
          <span className="text-muted-foreground mr-1">Or start with a persona:</span>
          {PERSONA_CHIPS.map((p) => (
            <button
              key={p.id}
              type="button"
              disabled={busy}
              onClick={() => createWithPersona.mutate(p.id)}
              title={p.description}
              className="inline-flex items-center rounded-full border border-border bg-card hover:bg-muted hover:border-accent/40 transition-colors px-3 py-1 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {p.label}
            </button>
          ))}
        </div>

        {(createSession.isError || createWithPersona.isError) && (
          <p role="alert" className="mt-6 text-center text-xs text-destructive">
            Couldn't start a new session. Check that the backend is reachable.
          </p>
        )}
      </div>
    </div>
  );
}
