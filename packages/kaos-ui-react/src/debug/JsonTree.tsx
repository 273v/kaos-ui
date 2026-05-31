/**
 * Interactive JSON tree with hover actions (copy path, copy value)
 * and inline expand/collapse.
 *
 * Ported from the Alpine 3 `jsonTree()` component in
 * `kaos_agents.examples.viewer.index.html`. The original was ~350
 * lines of pure JS + Alpine bindings; this React port keeps the same
 * visual + behavior surface:
 *
 *   - caret toggle ▸/▾ on objects/arrays
 *   - copy-path button copies a dotted/bracketed JSON path
 *   - copy-value button copies the JSON-stringified value
 *   - long strings (> 120 chars by default) get a preview + toggle
 *   - `{_redacted: true}` objects render with a byte-count + sha badge
 *   - collapsed preview shows `{N keys}` / `[N items]`
 *
 * Styling uses the `.kaos-jt-*` plain-CSS classes shipped with the
 * package's tokens.css so consumers can render the tree even without
 * Tailwind (the JSON viewer is supposed to look the same everywhere).
 */

import { ChevronDown, ChevronRight, Copy, Link2 } from "lucide-react";
import { useMemo, useState } from "react";

export interface JsonTreeProps {
  /** The value to render. Strings, numbers, booleans, null, objects, arrays. */
  value: unknown;
  /** Initial expand depth (defaults to 2). */
  initialDepth?: number;
  /** Long-string preview threshold in chars. Strings over this length get a toggle. */
  longStringThreshold?: number;
  /** Optional className appended to the root container. */
  className?: string;
}

type Path = ReadonlyArray<string | number>;

function pathToString(path: Path): string {
  let out = "";
  for (const seg of path) {
    if (typeof seg === "number") {
      out += `[${seg}]`;
    } else if (/^[A-Za-z_$][\w$]*$/.test(seg)) {
      out += out ? `.${seg}` : seg;
    } else {
      out += `[${JSON.stringify(seg)}]`;
    }
  }
  return out || "$";
}

function copyToClipboard(text: string): void {
  // navigator.clipboard requires HTTPS or localhost; fall back to a
  // synthetic textarea for older / insecure contexts so the action
  // never silently fails.
  if (typeof navigator !== "undefined" && navigator.clipboard) {
    void navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand("copy");
  } catch {
    // best-effort
  }
  document.body.removeChild(ta);
}

interface NodeProps {
  value: unknown;
  path: Path;
  depth: number;
  initialDepth: number;
  longStringThreshold: number;
  keyLabel?: string | number;
}

function JsonNode(props: NodeProps) {
  const { value, path, depth, initialDepth, longStringThreshold, keyLabel } = props;
  const [open, setOpen] = useState(depth < initialDepth);
  const [showFull, setShowFull] = useState(false);

  const isObj = value !== null && typeof value === "object" && !Array.isArray(value);
  const isArr = Array.isArray(value);
  const _isComplex = isObj || isArr;

  const keyEl =
    keyLabel === undefined ? null : (
      <span className="kaos-jt-key">
        {typeof keyLabel === "number" ? keyLabel : JSON.stringify(keyLabel)}
        <span className="kaos-jt-punct">: </span>
      </span>
    );

  const actions = (
    <span className="ml-2 inline-flex gap-1 opacity-0 hover:opacity-100 group-hover:opacity-100 transition-opacity">
      <button
        type="button"
        className="kaos-jt-meta hover:text-foreground"
        title={`Copy path: ${pathToString(path)}`}
        onClick={() => copyToClipboard(pathToString(path))}
        aria-label="Copy path"
      >
        <Link2 className="inline h-3 w-3" />
      </button>
      <button
        type="button"
        className="kaos-jt-meta hover:text-foreground"
        title="Copy value"
        onClick={() => copyToClipboard(JSON.stringify(value))}
        aria-label="Copy value"
      >
        <Copy className="inline h-3 w-3" />
      </button>
    </span>
  );

  // ─── primitive renderers ───────────────────────────────────────
  if (value === null) {
    return (
      <div className="kaos-jt-row group">
        {keyEl}
        <span className="kaos-jt-null">null</span>
        {actions}
      </div>
    );
  }
  if (typeof value === "boolean") {
    return (
      <div className="kaos-jt-row group">
        {keyEl}
        <span className="kaos-jt-bool">{String(value)}</span>
        {actions}
      </div>
    );
  }
  if (typeof value === "number") {
    return (
      <div className="kaos-jt-row group">
        {keyEl}
        <span className="kaos-jt-num">{value}</span>
        {actions}
      </div>
    );
  }
  if (typeof value === "string") {
    const long = value.length > longStringThreshold;
    const display = !showFull && long ? `${value.slice(0, longStringThreshold)}…` : value;
    return (
      <div className="kaos-jt-row group">
        {keyEl}
        <span className="kaos-jt-str break-words">"{display}"</span>
        {long && (
          <button
            type="button"
            className="kaos-jt-meta hover:text-foreground ml-1 text-[10px]"
            onClick={() => setShowFull((v) => !v)}
          >
            {showFull ? "less" : `+${value.length - longStringThreshold} more`}
          </button>
        )}
        {actions}
      </div>
    );
  }

  // ─── complex (object / array) ──────────────────────────────────
  if (isObj && (value as Record<string, unknown>)._redacted === true) {
    const v = value as Record<string, unknown>;
    return (
      <div className="kaos-jt-row group">
        {keyEl}
        <span className="kaos-jt-meta">
          [redacted{typeof v.bytes === "number" ? ` · ${v.bytes} bytes` : ""}
          {typeof v.sha === "string" ? ` · sha=${v.sha.slice(0, 8)}` : ""}]
        </span>
        {actions}
      </div>
    );
  }

  const entries: ReadonlyArray<readonly [string | number, unknown]> = isArr
    ? (value as unknown[]).map((v, i) => [i, v] as const)
    : Object.entries(value as Record<string, unknown>);

  const openBracket = isArr ? "[" : "{";
  const closeBracket = isArr ? "]" : "}";
  const count = entries.length;

  if (count === 0) {
    return (
      <div className="kaos-jt-row group">
        {keyEl}
        <span className="kaos-jt-punct">
          {openBracket}
          {closeBracket}
        </span>
        {actions}
      </div>
    );
  }

  return (
    <div className="group">
      <div className="kaos-jt-row">
        <button
          type="button"
          className="kaos-jt-caret"
          aria-expanded={open}
          aria-label={open ? "Collapse" : "Expand"}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? (
            <ChevronDown className="h-3 w-3 inline" />
          ) : (
            <ChevronRight className="h-3 w-3 inline" />
          )}
        </button>
        {keyEl}
        {!open ? (
          <span className="kaos-jt-meta">
            {openBracket}
            {isArr
              ? `${count} item${count === 1 ? "" : "s"}`
              : `${count} key${count === 1 ? "" : "s"}`}
            {closeBracket}
          </span>
        ) : (
          <span className="kaos-jt-punct">{openBracket}</span>
        )}
        {actions}
      </div>
      {open && (
        <>
          <div className="kaos-jt-children">
            {entries.map(([k, v]) => (
              <JsonNode
                key={String(k)}
                value={v}
                path={[...path, k]}
                depth={depth + 1}
                initialDepth={initialDepth}
                longStringThreshold={longStringThreshold}
                keyLabel={k}
              />
            ))}
          </div>
          <div className="kaos-jt-row">
            <span className="kaos-jt-caret" aria-hidden />
            <span className="kaos-jt-punct">{closeBracket}</span>
          </div>
        </>
      )}
    </div>
  );
}

export function JsonTree({
  value,
  initialDepth = 2,
  longStringThreshold = 120,
  className,
}: JsonTreeProps) {
  // Memo on identity so an expanded subtree doesn't re-mount when a
  // parent re-renders with the same value reference.
  const node = useMemo(
    () => (
      <JsonNode
        value={value}
        path={[]}
        depth={0}
        initialDepth={initialDepth}
        longStringThreshold={longStringThreshold}
      />
    ),
    [value, initialDepth, longStringThreshold],
  );
  return <div className={`kaos-jt ${className ?? ""}`}>{node}</div>;
}

// Internal helper exposed for tests / consumers building their own
// tree-style views.
export { pathToString };
