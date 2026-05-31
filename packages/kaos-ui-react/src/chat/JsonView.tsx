/**
 * Pretty-printed + syntax-highlighted JSON renderer.
 *
 * Used by `ToolCallBlock`'s "show raw" affordance and by any
 * structured-result expander that wants to show full-fidelity JSON
 * without dumping it into a `<pre>` of unstyled text.
 *
 * The renderer is intentionally simple — no jsonschema, no tree
 * widgets, no react-json-view dependency. It takes any value, calls
 * `JSON.stringify(value, null, 2)`, then runs one regex pass that
 * splits the indented output into typed spans (`key`, `string`,
 * `number`, `boolean`, `null`, `punctuation`). The semantic spans
 * carry distinct colors so a reader can see structure at a glance —
 * keys in blue, strings in green, scalars in muted accent — without
 * cluttering the chip with framed tree nodes.
 *
 * For *truncated* input (where `JSON.parse` would refuse the whole
 * blob) the caller is expected to repair with
 * :func:`repairAndParseJson` from `tool-formatters` first; this
 * component is purely about display.
 */

interface Props {
  /** Any JSON-serializable value. ``null`` / ``undefined`` renders nothing. */
  value: unknown;
  /** Max-height of the scrollable region (px). Defaults to 320. */
  maxHeight?: number;
  /** Add a "kaos-agents truncated the wire preview" footnote. */
  truncated?: boolean;
}

// Patterns ordered so the longest / most-specific wins. Run as a
// single alternation per token; non-overlapping by construction.
const TOKEN_RE =
  // 1) string keys: `"foo":` (note the trailing colon)
  /("(?:\\.|[^"\\])*")(\s*:)|/.source +
  // 2) string values
  /("(?:\\.|[^"\\])*")|/.source +
  // 3) boolean / null
  /\b(true|false|null)\b|/.source +
  // 4) numbers (incl. scientific)
  /(-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|/.source +
  // 5) punctuation
  /([{}\[\],])/.source;

const TOKEN = new RegExp(TOKEN_RE, "g");

function renderHighlighted(json: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let i = 0;
  let key = 0;
  for (const m of json.matchAll(TOKEN)) {
    if (m.index! > i) {
      out.push(json.slice(i, m.index!));
    }
    const [, keyMatch, colon, str, kw, num, punct] = m;
    if (keyMatch) {
      out.push(
        <span key={key++} className="text-sky-700 dark:text-sky-300">
          {keyMatch}
        </span>,
      );
      if (colon) out.push(<span key={key++}>{colon}</span>);
    } else if (str) {
      out.push(
        <span key={key++} className="text-emerald-700 dark:text-emerald-300">
          {str}
        </span>,
      );
    } else if (kw) {
      out.push(
        <span key={key++} className="text-violet-700 dark:text-violet-300">
          {kw}
        </span>,
      );
    } else if (num) {
      out.push(
        <span key={key++} className="text-amber-700 dark:text-amber-300">
          {num}
        </span>,
      );
    } else if (punct) {
      out.push(
        <span key={key++} className="text-muted-foreground">
          {punct}
        </span>,
      );
    }
    i = m.index! + m[0].length;
  }
  if (i < json.length) out.push(json.slice(i));
  return out;
}

export function JsonView({ value, maxHeight = 320, truncated = false }: Props) {
  if (value == null) return null;
  let json: string;
  try {
    json = JSON.stringify(value, null, 2);
  } catch {
    return (
      <pre className="font-mono bg-muted rounded px-2 py-1 text-[11px]">
        (value is not JSON-serializable)
      </pre>
    );
  }
  return (
    <div className="rounded border border-border/60 bg-background overflow-hidden">
      <pre
        className="font-mono text-[11px] leading-relaxed px-3 py-2 overflow-y-auto"
        style={{ maxHeight }}
      >
        {renderHighlighted(json)}
      </pre>
      {truncated && (
        <div className="px-3 py-1 border-t border-border/60 text-[10px] italic text-muted-foreground bg-muted/30">
          kaos-agents truncated the wire preview at ~200 chars; only the fields shown above arrived
          intact.
        </div>
      )}
    </div>
  );
}
