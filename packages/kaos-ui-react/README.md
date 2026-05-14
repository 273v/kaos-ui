# @273v/kaos-ui-react

[![npm](https://img.shields.io/npm/v/@273v/kaos-ui-react.svg?label=npm)](https://www.npmjs.com/package/@273v/kaos-ui-react)
[![license](https://img.shields.io/npm/l/@273v/kaos-ui-react.svg)](./LICENSE)
[![types](https://img.shields.io/npm/types/@273v/kaos-ui-react.svg)](./dist/index.d.ts)

React UI primitives for [kaos-agents](https://github.com/273v/kaos-agents)-
powered chat surfaces. Drop-in chat composer, transcript, file
upload, citations panel, document explorer, and a live "Run
Inspector" debugger — backend-agnostic via a single
`<KaosUIProvider transport={…}>` at app root.

> **Alpha — API subject to change before 0.1.0.** Pin an exact
> version in your `package.json` until the API stabilizes.

## Install

```bash
pnpm add @273v/kaos-ui-react @tanstack/react-query
```

Peer dependencies (all required at runtime):

| Peer | Range | Why |
|------|-------|-----|
| `react` | `>=19` | Components use the React 19 runtime. |
| `react-dom` | `>=19` | Same. |
| `@tanstack/react-query` | `>=5` | Hooks use `useQuery` / `useMutation`. |
| `tailwindcss` | `>=4` | Optional. Required only if you use the bundled Tailwind preset; otherwise the package's CSS variables work standalone. |

## Quick start

```tsx
// main.tsx
import "@273v/kaos-ui-react/styles.css";
import { KaosUIProvider, type Transport } from "@273v/kaos-ui-react/lib";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

const queryClient = new QueryClient();

const transport: Transport = {
  baseUrl: "/v1/chat",
  getToken: () => localStorage.getItem("kaos:token"),
};

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <KaosUIProvider transport={transport}>
        <App />
      </KaosUIProvider>
    </QueryClientProvider>
  </StrictMode>,
);
```

```tsx
// App.tsx — a minimal chat
import {
  Composer,
  Message,
  TurnStatus,
} from "@273v/kaos-ui-react/chat";
import { useSendMessage } from "@273v/kaos-ui-react/hooks";
import { useState } from "react";

export function App() {
  const [input, setInput] = useState("");
  const stream = useSendMessage({ sessionId: "demo" });

  return (
    <div className="flex h-screen flex-col">
      <div className="flex-1 overflow-y-auto px-6 py-8">
        {stream.state.messages.map((m) => (
          <Message key={m.id} message={m} />
        ))}
        <TurnStatus status={stream.state.status} />
      </div>
      <Composer
        value={input}
        onChange={setInput}
        onSubmit={() => {
          if (!input.trim() || stream.state.pending) return;
          stream.send(input);
          setInput("");
        }}
        onStop={stream.abort}
        pending={stream.state.pending}
      />
    </div>
  );
}
```

## What's in the package

| Subpath | Highlights |
|---|---|
| `@273v/kaos-ui-react/chat` | `Composer`, `Message`, `MessageMarkdown`, `TurnStatus`, `ToolCallBlock`, `UsageChip`, `DropZone`, `FileChips`, `CitationsPanel`, `DocumentExplorer`, `ModelPicker` |
| `@273v/kaos-ui-react/debug` | `RunInspector`, `CostStrip`, `EventsLog`, `FilterChips`, `JsonTree` |
| `@273v/kaos-ui-react/hooks` | `useSendMessage`, `useSessionFiles`, `useUploadFile`, `useDeleteFile`, `useBackfillFiles`, `useCitations`, `useCostAggregation`, `useTransport` |
| `@273v/kaos-ui-react/lib` | `KaosUIProvider`, `Transport`, `KaosAgentEvent` union, `applyEvent` reducer, `renderMarkdown`, citation + file types, `transportFetch` / `transportJson` |
| `@273v/kaos-ui-react/styles.css` | Theme tokens + JSON-tree + markdown base styles |
| `@273v/kaos-ui-react/tailwind.preset` | Tailwind 4 preset mapping CSS variables → theme.colors |

Subpath imports are recommended for production builds — they
tree-shake by domain. The root export re-exports everything for
convenience during prototyping.

## The Transport contract

`<KaosUIProvider transport={…}>` is the one piece of plumbing every
host app needs to provide. The `Transport` shape is intentionally
minimal:

```ts
interface Transport {
  /** URL prefix for every request (`"/v1/chat"`, full origin, etc.).
   *  Trailing slash optional; the helper normalizes. */
  baseUrl: string;
  /** Bearer token getter — called per-request so you can rotate
   *  tokens without remounting. Return `null` to skip auth. */
  getToken?: () => string | null | undefined;
  /** Optional custom fetch (msw, retry wrapper, …). Defaults to
   *  global fetch. */
  fetch?: typeof fetch;
}
```

The package's hooks expect a kaos-agents-flavored backend:

- `POST {baseUrl}/sessions/{id}/messages` — SSE stream of the 15 wire
  events
- `GET {baseUrl}/sessions/{id}/files` — upload list
- `POST {baseUrl}/sessions/{id}/files` — multipart upload
- `DELETE {baseUrl}/sessions/{id}/files/{filename}` — delete
- `POST {baseUrl}/sessions/{id}/files:backfill` — recompute token
  counts + summaries
- `POST {baseUrl}/sessions/{id}/citations` — citation extraction

Any backend matching those shapes works. If yours uses different
paths, you can either subclass the hooks via `transportFetch` /
`transportJson` directly, or open an issue and we'll consider a
configurable URL-template option.

## Theming

The CSS variables in `styles.css` are the single point of truth for
the surface palette:

```css
:root {
  --kaos-background: 0 0% 100%;
  --kaos-foreground: 222 47% 11%;
  --kaos-card: 0 0% 100%;
  --kaos-muted: 210 40% 96%;
  --kaos-primary: 222 47% 11%;
  --kaos-destructive: 0 84% 60%;
  /* …plus dark-mode overrides under `:root.dark` / `html.dark` */
}
```

Override them in your own stylesheet — the components don't care
where the values come from:

```css
:root {
  --kaos-primary: 273 70% 50%; /* 273V brand purple */
}
```

If you're already on Tailwind 4, the included preset maps these
variables to theme colors:

```ts
// tailwind.config.ts
import kaosPreset from "@273v/kaos-ui-react/tailwind.preset";

export default {
  presets: [kaosPreset],
  content: [
    "./src/**/*.{ts,tsx}",
    "./node_modules/@273v/kaos-ui-react/dist/**/*.{js,mjs,cjs}",
  ],
};
```

The JSON tree palette (`--jt-key`, `--jt-str`, …) is themed
separately so it can stay legible on any background.

## Wire constraints worth knowing

The package targets [kaos-agents 0.1.0a1](https://pypi.org/project/kaos-agents/0.1.0a1/).
A few quirks of that release shape the API:

- **Tool result truncation.** `span/tool_call/complete` events carry
  `attributes.result_summary` truncated to 200 chars. Anything that
  needs the full result (e.g., the citations panel) must run a
  second pass against an endpoint that returns the structured data.
  The `useCitations` hook does this post-turn via
  `POST /sessions/{id}/citations`.
- **No corpus parameter.** `MessageRequest` has no `corpus=` field,
  so the consuming app inlines uploaded-document context into the
  system prompt instead. The example app's `stream_proxy` shows the
  pattern.
- **No turn linking in memory/actions.** kaos-agents persists action
  records but doesn't tag them with a `message_id` or `turn_id`. To
  hydrate `tool_calls` on past assistant messages, the host app
  must tap the SSE stream and persist its own per-turn sidecar
  (see `app/services/tool_call_recorder.py` in the
  single-user-chat example).

Once kaos-agents lands these upstream, the workarounds collapse.

## Live debug — Run Inspector

```tsx
import { RunInspector } from "@273v/kaos-ui-react/debug";

<RunInspector
  events={stream.rawEvents}
  open={inspectorOpen}
  onClose={() => setInspectorOpen(false)}
/>
```

Three panels stacked: live cost / tokens / call count, a category
filter chip row, and a scrollable event log where each row expands
into a `<JsonTree>` of the raw event payload. Modeled after the
[`kaos-agents` JSONL viewer](https://github.com/273v/kaos-agents/tree/main/kaos_agents/examples/viewer)
but adapted to a live SSE stream.

## Versioning

`0.1.0-alpha.x` releases may break the API at any point. We'll
ship `0.1.0` once:

1. The Transport contract has been validated against ≥2 different
   backend shapes (single-user-chat + multi-user-chat).
2. The kaos-agents 0.1.0a2 release lands and the
   `<KaosUIProvider>` doesn't need to know about the wire
   workarounds.
3. The Storybook (or equivalent component sandbox) is up so
   consumers can sanity-check before upgrading.

## License

[Apache 2.0](./LICENSE). © 273 Ventures, LLC.

## Contributing

This package lives in the
[`273v/kaos-ui`](https://github.com/273v/kaos-ui) monorepo. See the
repo's [`CONTRIBUTING.md`](https://github.com/273v/kaos-ui/blob/main/CONTRIBUTING.md)
for ground rules. Issues, PRs, and design feedback all welcome.
