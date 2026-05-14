# single-user-chat — UX & Visual Language

> Status: draft. Sources: competitive research against Harvey, Legora, Midpage, Mike (willchen96/mike, OSS legal AI), and Claude.ai, cross-checked against the existing `packages/ui` design tokens at `templates/web/spa/packages/ui/src/styles/globals.css`. Last updated: 2026-05-14.

This document is the design spec for the single-user-chat example. It exists because `packages/ui` defines tokens but not composition; we want every component decision pre-resolved before any TSX is written so the example reads as a cohesive product, not a collage of shadcn defaults.

## 1. Anchor points (what's already settled)

From `packages/ui/src/styles/globals.css`:

- **Palette**: warmed-stone OKLCH neutrals (`oklch(0.984 0.003 85)` paper, drift hue ~80–90°).
- **Primary**: near-black `oklch(0.197 0.003 85)`. **Not blue.**
- **Accent**: amber-700 `oklch(0.561 0.158 60)` — citations, links, active states only.
- **Border**: 1 px hairline `oklch(0.910 0.005 80)`. We use borders, not shadows.
- **Radius**: 8 px base. Sm/md/lg/xl derived.
- **Type**: Inter Variable (sans), Source Serif 4 Variable (serif), JetBrains Mono.

These are non-negotiable. Everything below composes on top.

## 2. Competitive landscape

| Product | Layout | Conversation | Composer | Tool/reasoning surface | Palette |
|---|---|---|---|---|---|
| **Harvey** | Two-column. Unified Assistant: chat + drafting in one thread. ([rebuild](https://www.harvey.ai/blog/rebuilding-harveys-design-system-from-the-ground-up), [unified](https://www.harvey.ai/blog/a-more-unified-harvey-experience)) | Centered max-width thread, sentence-level citations as linked refs. | Single composer w/ matter & vault selectors near input. | "Paper trail of thinking steps" — anti-black-box, explicit. ([approach](https://www.harvey.ai/blog/how-we-approach-design-at-harvey)) | "hy-" tokens, amber + olive + jade. No shadows. |
| **Legora** | Multi-surface — web app, Word, Outlook, mobile. Tabular Review grid (rows=docs, cols=prompts). ([product](https://legora.com/product)) | Assistant follows you across surfaces. Built on Claude. | Ribbon in Word + web composer. | "aOS" framing — workflow runs are first-class. | High-contrast Stockholm minimal, restrained palette. |
| **Midpage** | Two-column standalone + Claude/ChatGPT plugin. Caselaw-grid view. ([midpage](https://www.midpage.ai/)) | Treatment-signal pills (neg/caution/neutral). Chat anchored to a "Notebook" of saved cases. | Bottom composer + cite-check upload. | Citator results as inline signal pills. | Lighter, Westlaw-adjacent density. |
| **Mike (OSS)** | Two-column, `w-64` (256 px) sidebar → `w-14` collapsed. `bg-gray-50` + hairline border. ([layout.tsx](https://github.com/willchen96/mike/blob/main/frontend/src/app/(pages)/layout.tsx)) | Centered `max-w-4xl` thread. Serif empty state ("Hi, {name}", `text-4xl font-serif font-light`). ([InitialView](https://github.com/willchen96/mike/blob/main/frontend/src/app/components/assistant/InitialView.tsx)) | Chip row above textarea: Add-Doc / Workflow / Projects / Model toggle. Send arrow inside textarea. ([ChatInput](https://github.com/willchen96/mike/blob/main/frontend/src/app/components/assistant/ChatInput.tsx)) | `AssistantMessage.tsx` (65 KB!) + separate `AssistantSidePanel.tsx`. Inline reasoning + side panel for heavy artifacts. | **Blue primary** `rgb(0,136,255)` ← consumer tell. EB Garamond serif. |
| **Claude.ai** | Two-column. Left rail: "New chat" pinned top + Starred + Recents. `Ctrl+.` toggle. | Centered single column, flat role-labeled blocks (no bubbles). Skeleton/streaming caret. | Centered bottom composer + attach + model picker. | Inline labeled block, expandable. Heavy artifacts → right-rail "Artifacts" panel. | Warm cream / dark luxury. Serif logo, sans body. |

## 3. What kaos-ui is already doing right

Cite-checks the existing tokens against best-of-class:

- **Warm-stone neutrals, not pure white** — matches Harvey's "deeply familiar, yet unmistakably modern." Mike's `bg-white` reads consumer by contrast.
- **Near-black primary, not blue** — Claude.ai and Harvey both use neutral-on-neutral with a single warm accent. Mike's blue is exactly what we deflect.
- **Amber-700 accent** — aligns with Harvey's amber/olive/jade family. An editorial accent, not Tailwind sky-500.
- **1 px hairlines, no shadows** — Harvey's UI refresh ([release notes](https://help.harvey.ai/release-notes/design-system-refresh)) emphasized hairlines for region separation; we match.
- **8 px radius** — tighter than shadcn default (10 px) and Mike (10 px). Reads more legal-product, less consumer-chat.
- **Inter + Source Serif 4** — mirrors Mike's Inter + EB Garamond pairing. Source Serif 4 is the better-engineered serif.

## 4. Adopted patterns (decisions for this example)

### 4.1 App shell

- **Sidebar**: 264 px expanded, 56 px collapsed. Slightly wider than Mike's 256 px to give Source Serif 4 headings room. `bg-secondary` (warm-paper), `border-r border-border`.
- **Collapse state persisted to `localStorage`.**
- **Top of sidebar**: serif app name + "New chat" primary button stacked. Recents below.
- **Bottom of sidebar**: user avatar / settings trigger (`Sheet` opens from the right).
- **Keyboard**: `Cmd/Ctrl+B` toggles sidebar. `Cmd/Ctrl+K` opens "New chat." `Cmd/Ctrl+J/K` navigates session list. `Escape` closes drawer.
- **Right rail**: collapsed by default; appears at 384 px (`w-96`) when an assistant message has a "View in panel" target (tool result preview, long artifact, citation source list).

### 4.2 Conversation surface

- **Max width**: `max-w-4xl` (896 px), centered.
- **Layout**: flat role-labeled blocks. **No bubbles.** No `bg-blue-500` user message, no `bg-gray-100` assistant card.
- **Role label**: small serif `You` / `Assistant` / `Tool` / `Error` above each block, in `text-muted-foreground`. Time stamp inline on hover.
- **Spacing**: `gap-8` between turns, `gap-2` within a turn's blocks.
- **Streaming indicator**: 1-line italic "Thinking…" in `text-muted-foreground` shown when the agent is between tokens (tool call running, model pre-token-latency); replaced by streaming text + cursor caret (`▍`, blinking at 1 Hz) once a `TextDelta` arrives.
- **Disclaimer line** (bottom-fixed below composer, `text-xs text-muted-foreground`): "AI output is informational. Not legal advice. Verify before relying."

### 4.3 Composer

- **Position**: bottom-sticky inside the centered column, `max-w-3xl` (768 px). Narrower than the message column so it reads as anchored, not edge-to-edge.
- **Textarea**: auto-grow on input (`el.scrollHeight`), min height ~56 px, max ~280 px before scroll.
- **Chip row** above the textarea, left-aligned:
  - **Model picker** (always visible). Renders the current model id label; click opens a popover with the catalog.
  - **Attach** (disabled placeholder in v1, opacity-50, tooltip "Coming soon"). Reserves visual real estate so v2 isn't a layout shift.
- **Send button**: arrow icon, inside the textarea, right-aligned. Disabled when `pending` or `value.trim() === ""`.
- **No matter selector, no tone selector, no sources picker.** Out of v1 scope. Mike has these; we reject for now.
- **Keyboard**: Enter = send. Shift+Enter = newline. Cmd+Enter also sends (Mac users expect it).

### 4.4 Tool-call display

- **Default render**: inside the assistant message, a collapsed `<details>` block titled with the tool name + status icon (`◐` running / `✓` done / `✕` error). Click to expand args + result.
- **Heavy artifacts**: tools that emit large text or a structured artifact (PDF page render, table) render a "View in panel" button inside the expanded block. Click → opens the right-rail panel with the full content. The right rail is the same panel Claude.ai uses for Artifacts.
- **Order**: tool calls render inline in the order they appear in the event stream. No separate "Actions" tab. Fragmenting the reading flow is an anti-pattern.

### 4.5 Citation display (planned, post-v1)

- Inline numbered superscripts `[1]` in `--accent` (amber-700).
- A "Sources" right-rail panel lists the full reference list with linked source titles.
- We do **not** adopt Midpage's treatment-signal pills — caselaw-specific, doesn't generalize to chat.

### 4.6 Sidebar items

- Row height: `h-9` (36 px), `text-sm`, `px-3`, `rounded-md`.
- Truncate at row width.
- Hover: `bg-muted`.
- Active: `bg-muted text-foreground` + 2 px left-edge stripe in `--accent` (amber). This is our differentiator vs. Mike's flat-background active state — gives the eye a clear "you are here."
- Hover-revealed action menu (`MoreHorizontal` icon, `ghost` button): Rename, Export → Markdown, Export → JSON, Delete.
- Group divider for "Today" / "Yesterday" / "Last 7 days" / "Older" sections in the recents list.

### 4.7 Settings sheet

- Opens from the right (`Sheet` component from shadcn).
- Trigger: avatar/initials button at the bottom-left of the sidebar.
- Content: model default, system-prompt editor (current session), theme toggle (light/dark), API-key status (read-only badges).
- No tabs. One scrollable column.
- Save = optimistic update + server confirm. Cancel = close without persisting.

### 4.8 Empty state

- Centered column, no sidebar dependency.
- Serif greeting at `text-4xl font-serif font-light text-foreground`: "Welcome." or product name. No name-personalization in v1 (single user, single token).
- Muted subtitle on one line.
- Composer directly underneath.
- Disclaimer below.
- **No suggestion chips, no animated icons.** Mike's icon-slide-in is cute but reads consumer. A static greeting is more confident.

### 4.9 Empty session detail (new session, before first message)

- Same as empty state, plus a small "New conversation" label in `text-xs text-muted-foreground` above the greeting.

## 5. Deliberately rejected patterns

Out of scope or off-brand for v1. Listed so reviewers don't reopen them:

- **Matter / vault / project selector in composer.** Harvey, Mike, Legora all carry it. Single-user demo doesn't need scoping.
- **Tabular Review grid.** Legora's signature surface. Different product.
- **Word/Outlook add-in framing.** Not the kaos-ui demo's job.
- **In-doc editor with redlines.** Harvey + Mike both have it. Big surface area; out of scope.
- **Multi-provider API-key management UI.** Mike has Account → Models & API Keys. We read keys from `.env` only.
- **Animated empty-state choreography.** Cute, reads consumer.
- **Prompt-suggestion chips on empty state.** Implies a prompt library. We don't have one.

## 6. Anti-patterns to deflect

A vibe coder reading shadcn defaults will instinctively add these. The example must NOT.

| Anti-pattern | Why it's wrong here | What to do instead |
|---|---|---|
| Blue primary buttons (`bg-blue-500`) | Consumer SaaS tell; Mike does this and we explicitly reject. | Use `--primary` (warm near-black). |
| Drop shadows on cards/dropdowns/composer | Harvey/Legora/Midpage all use hairlines. | `border border-border`. Ban `shadow-sm` and above in the example app. |
| Gradient backgrounds (esp. purple→blue) | Instant ChatGPT-Plus tell. | Solid `bg-background` / `bg-secondary`. |
| Pill-shaped action buttons (`rounded-full`) | Reserved for status dots and avatars. | `rounded-md` (8 px). |
| Oversized rounded corners (`rounded-2xl+`) | Reads toy/consumer. | 8 px max. |
| Neon / saturated accents (cyan, lime, fuchsia) | Breaks the editorial palette. | Amber-700 only. |
| Speech bubbles | iMessage tell. | Flat role-labeled blocks. |
| Pulsing-dot "AI is thinking" | Consumer chat trope. | Streaming caret + italic "Thinking…" pill. |
| Multiple typefaces beyond sans/serif/mono | Google-Fonts roulette. | Inter Variable + Source Serif 4 Variable + JetBrains Mono. Period. |
| Promo banners / "Upgrade to Pro" CTAs / onboarding tours | This is a tool, not a funnel. | None. |
| Emoji in UI strings (✨ 🎉 🚀) | Reads consumer/promotional. | Lucide icons only, monochrome. |
| Color-coded role badges (green user, blue assistant) | Reads dashboard, not document. | Serif label, no color. |

## 7. Density target

Spacious, editorial. The kaos-ui design tokens are explicitly modeled on the Harvey/Legora/Midpage "luxury editorial" end of the spectrum, not the Westlaw "research-grid" end. Reading a single conversation should feel like reading a typeset document, not browsing a dashboard.

Targets:
- Body text: 14 px / 1.6 line-height.
- Section gap (turn to turn): 32 px.
- Internal gap (within a turn): 8–12 px.
- Sidebar font size: 13 px / 1.4 line-height.

## 8. Dark mode

Inherit from `packages/ui` `.dark` block. Test every component in both modes. Source Serif 4 holds up in dark; avoid setting `font-weight: 300` on it in dark mode where it gets thin.

## 9. Accessibility floor

- All interactive elements reachable via keyboard.
- Focus rings visible (1 px `--ring` per the existing tokens — do NOT bump to 2 px to "improve" visibility; the design tokens deliberately chose hairline).
- ARIA: `role="log"` + `aria-live="polite"` on the conversation surface; new messages announced as they finalize, not every delta.
- Color contrast ≥ AA on body text, ≥ AAA on disclaimer.
- Reduced-motion: disable cursor caret blink, disable any decorative animation. `prefers-reduced-motion` honored.

## 10. Sources

Harvey:
- [Rebuilding Harvey's Design System From the Ground Up](https://www.harvey.ai/blog/rebuilding-harveys-design-system-from-the-ground-up)
- [A More Unified Harvey Experience](https://www.harvey.ai/blog/a-more-unified-harvey-experience)
- [How We Approach Design at Harvey](https://www.harvey.ai/blog/how-we-approach-design-at-harvey)
- [UI Refresh release notes](https://help.harvey.ai/release-notes/design-system-refresh)
- [The Brief: April 2026](https://www.harvey.ai/blog/the-brief-april-2026)

Legora:
- [Product](https://legora.com/product)
- [AIVortex review](https://www.aivortex.io/legal/ai-tools/legora/)

Midpage:
- [midpage.ai](https://www.midpage.ai/)

Mike (Will Chen, OSS):
- [Repo](https://github.com/willchen96/mike)
- [Sidebar layout source](https://github.com/willchen96/mike/blob/main/frontend/src/app/(pages)/layout.tsx)
- [AppSidebar](https://github.com/willchen96/mike/blob/main/frontend/src/app/components/shared/AppSidebar.tsx)
- [InitialView (empty state)](https://github.com/willchen96/mike/blob/main/frontend/src/app/components/assistant/InitialView.tsx)
- [ChatInput (composer)](https://github.com/willchen96/mike/blob/main/frontend/src/app/components/assistant/ChatInput.tsx)
- [globals.css (tokens)](https://raw.githubusercontent.com/willchen96/mike/main/frontend/src/app/globals.css)
- [Artificial Lawyer interview](https://www.artificiallawyer.com/2026/05/04/mike-the-open-source-legal-ai-platform-will-chen-interview/)

Claude.ai:
- [Sidebar tutorial — Guideflow](https://www.guideflow.com/tutorial/how-to-open-the-sidebar-in-claudeai)
