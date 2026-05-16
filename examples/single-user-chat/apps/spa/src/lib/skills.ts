// Built-in skill catalog — the seed library shown in the composer
// slash menu. Each skill is a reusable (name, description, prefill,
// optional persona / model / tool-groups) tuple.
//
// Future: load these from `.kaos/skills/<id>/SKILL.md` on the
// backend so individual deployments can ship their own legal-
// research playbooks. For v0.1.0a7 we ship a curated default set.

import type { Skill } from "@273v/kaos-ui-react/chat";

export const BUILTIN_SKILLS: Skill[] = [
  {
    id: "fr-search",
    name: "Federal Register: latest rule",
    description: "Search FR for a recent rule and report it with citations.",
    persona: "research",
    allowed_groups: ["web", "documents", "citations", "vfs"],
    prefill:
      "Search the Federal Register for the most recent rule about {topic}.\n\nReturn:\n- Publication date\n- Issuing agency\n- FR document number\n- A 2-sentence plain-English summary",
  },
  {
    id: "summarize",
    name: "Summarize the attached document",
    description: "Structured summary with parties, governing law, key terms.",
    persona: "research",
    allowed_groups: ["documents", "citations", "vfs"],
    prefill:
      "Summarize the document I just uploaded. Structure the output as:\n\n- **Parties**\n- **Governing law**\n- **Key obligations**\n- **Termination**\n- **Unusual clauses**\n\nCite the source filename for each item.",
  },
  {
    id: "redline",
    name: "Draft a redline",
    description: "Author a memo, clause, or response with inline citations.",
    persona: "drafting",
    allowed_groups: ["documents", "citations", "vfs", "authoring"],
    prefill:
      "Draft a short memo on the implications of {topic} for {audience}.\n\nGround every claim in a citation. Use the standard memo structure (issue, short answer, analysis, conclusion).",
  },
  {
    id: "verify",
    name: "Verify a citation or claim",
    description: "Pull source text and confirm what's actually said.",
    persona: "research",
    allowed_groups: ["web", "documents", "citations", "vfs", "retrieval"],
    prefill:
      "Find {citation} and quote the part that defines / states {phrase}.\n\nIf the source contradicts the claim, say so explicitly with the quote.",
  },
  {
    id: "compare",
    name: "Compare N documents",
    description: "Side-by-side table comparison of an uploaded doc set.",
    persona: "research",
    allowed_groups: ["documents", "citations", "vfs"],
    prefill:
      "Compare the documents I uploaded across these axes:\n\n- Governing law\n- Effective date\n- Term length\n- Renewal mechanism\n- Termination\n- Unusual clauses\n\nReturn as a table; cite the source filename per cell.",
  },
  {
    id: "forensics",
    name: "Forensics: search uploaded corpus",
    description: "Local-only research over an uploaded file set; no web egress.",
    persona: "forensics",
    allowed_groups: ["forensics", "vfs"],
    prefill:
      "Search the uploaded corpus for {query}.\n\nReturn every match with the source filename, page number (or section), and a 2-sentence quote-bracketed excerpt.",
  },
];
