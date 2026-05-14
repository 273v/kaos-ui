# @273v/kaos-ui-react

React UI primitives for [kaos-agents](https://github.com/273v/kaos-agents)-powered chat surfaces.

Drop-in chat composer, transcript, file upload, citations panel, and a live "Run Inspector" debugger — backend-agnostic via a single `<KaosUIProvider transport={...}>` at app root.

> Alpha — API subject to change before 0.1.0.

## Install

```bash
pnpm add @273v/kaos-ui-react @tanstack/react-query
```

Peer deps: `react >=19`, `react-dom >=19`, `@tanstack/react-query >=5`, `tailwindcss >=4` (optional — only if you use the provided preset).

## Wire it up

```tsx
import { KaosUIProvider, Composer, RunInspector } from "@273v/kaos-ui-react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@273v/kaos-ui-react/styles.css";

const qc = new QueryClient();

export function App() {
  return (
    <QueryClientProvider client={qc}>
      <KaosUIProvider
        transport={{
          baseUrl: "/v1/chat",
          getToken: () => localStorage.getItem("token"),
        }}
      >
        <Composer onSubmit={...} />
        <RunInspector />
      </KaosUIProvider>
    </QueryClientProvider>
  );
}
```

## What's in the package

| Subpath | What it exports |
|---|---|
| `/chat` | `Composer`, `Message`, `MessageMarkdown`, `TurnStatus`, `DropZone`, `FileChips`, `CitationsPanel`, `ModelPicker` |
| `/debug` | `RunInspector`, `CostStrip`, `EventsLog`, `JsonTree`, `FilterChips` |
| `/hooks` | `useSendMessage`, `useCitations`, `useCostAggregation`, `useFileUpload`, `useTransport` |
| `/lib` | `KaosAgentEvent` union, `applyEvent` reducer, `Transport` interface, markdown helpers |
| `/styles.css` | Theme tokens + JSON-tree + markdown base styles |
| `/tailwind.preset` | Tailwind 4 preset mapping the CSS variables to theme colors |

## License

Apache-2.0. © 273 Ventures, LLC.
