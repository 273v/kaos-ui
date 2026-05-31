import { Link } from "@tanstack/react-router";
import {
  Archive,
  Check,
  Download,
  FileJson,
  FileText,
  MoreHorizontal,
  Pencil,
  Star,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useArchiveSession } from "@/hooks/use-archive-session";
import { useHealth } from "@/hooks/use-health";
import { usePatchMeta } from "@/hooks/use-patch-meta";
import { apiFetch } from "@/lib/api-fetch";
import type { SessionSummary } from "@/lib/api-types";

interface Props {
  session: SessionSummary;
  active: boolean;
}

/**
 * Single sidebar row. h-9 height per UX-LANGUAGE § 4.6.
 *
 * Affordances (from left to right):
 *   - active stripe (2px accent on the left edge when on this route)
 *   - star toggle (always visible; filled when starred)
 *   - session title (link, or inline-editable input when renaming)
 *   - message count pill (only shown when > 0)
 *   - "…" menu (rename / archive) — hover-revealed
 *
 * The menu and the rename input share an effect for click-outside +
 * Escape close so they behave predictably together.
 */
export function SessionListItem({ session, active }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [draftTitle, setDraftTitle] = useState(session.title);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const renameInputRef = useRef<HTMLInputElement | null>(null);
  const archive = useArchiveSession();
  const patch = usePatchMeta(session.id);
  const health = useHealth();

  // P3-10 stale-session badge: the session was created on a different
  // build than the one currently running. We only badge when BOTH
  // SHAs are known — `build_sha === undefined/null` means the
  // session predates P3-10 tracking and we have no signal either way.
  const currentBuild = health.data?.build_sha;
  const sessionBuild = session.build_sha;
  const isStaleBuild =
    typeof currentBuild === "string" &&
    typeof sessionBuild === "string" &&
    currentBuild !== sessionBuild;

  const commitRename = useCallback(() => {
    const trimmed = draftTitle.trim();
    if (trimmed && trimmed !== session.title) {
      patch.mutate({ title: trimmed });
    }
    setRenaming(false);
  }, [draftTitle, session.title, patch]);

  // Click-outside / Escape closes the menu OR commits-then-closes the rename.
  useEffect(() => {
    if (!menuOpen && !renaming) return;
    const onDocClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (menuOpen && menuRef.current && !menuRef.current.contains(target)) {
        setMenuOpen(false);
      }
      if (renaming && renameInputRef.current && !renameInputRef.current.contains(target)) {
        commitRename();
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenuOpen(false);
        if (renaming) {
          setDraftTitle(session.title);
          setRenaming(false);
        }
      }
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen, renaming, session.title, commitRename]);

  useEffect(() => {
    if (renaming) {
      renameInputRef.current?.focus();
      renameInputRef.current?.select();
    }
  }, [renaming]);

  const onStarClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    patch.mutate({ starred: !session.starred });
  };

  return (
    <div className="group relative">
      {active && (
        <span
          aria-hidden
          className="absolute left-0 top-1.5 bottom-1.5 w-[2px] bg-accent rounded-full"
        />
      )}
      <div className="flex items-stretch">
        <button
          type="button"
          onClick={onStarClick}
          aria-label={session.starred ? "Unstar session" : "Star session"}
          aria-pressed={session.starred}
          className={`ml-1 mr-1 self-center h-7 w-6 inline-flex items-center justify-center rounded-md hover:bg-muted ${
            session.starred
              ? "text-warn opacity-100"
              : "text-muted-foreground opacity-50 group-hover:opacity-100"
          }`}
        >
          <Star
            className="h-3.5 w-3.5"
            fill={session.starred ? "currentColor" : "none"}
            strokeWidth={session.starred ? 1.5 : 2}
          />
        </button>

        {renaming ? (
          <div className="flex items-center h-9 flex-1 min-w-0 gap-1 pr-1">
            <input
              ref={renameInputRef}
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commitRename();
                }
              }}
              maxLength={120}
              className="flex-1 min-w-0 h-7 px-2 rounded-md border border-input bg-background text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <button
              type="button"
              onClick={commitRename}
              aria-label="Save title"
              className="shrink-0 h-7 w-7 inline-flex items-center justify-center rounded-md hover:bg-muted text-foreground"
            >
              <Check className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() => {
                setDraftTitle(session.title);
                setRenaming(false);
              }}
              aria-label="Cancel rename"
              className="shrink-0 h-7 w-7 inline-flex items-center justify-center rounded-md hover:bg-muted text-muted-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : (
          <>
            {/*
              Sidebar row — anchored at 13px text (UI chrome size).
              Active state uses an inline left-edge stripe in the
              accent color (UX-LANGUAGE.md §4.6) instead of the
              softer bg-muted fill, which now signals hover only.
            */}
            <Link
              to="/sessions/$id"
              params={{ id: session.id }}
              className={`relative flex items-center h-8 pl-3 pr-2 rounded-md text-[13px] leading-tight transition-colors flex-1 min-w-0 gap-2 ${
                active
                  ? "bg-muted/70 text-foreground font-medium before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-0.5 before:rounded-full before:bg-accent"
                  : "text-foreground/85 hover:bg-muted hover:text-foreground"
              }`}
              title={session.title}
            >
              <span className="truncate flex-1">{session.title || "Untitled"}</span>
              {isStaleBuild && (
                <span
                  role="status"
                  aria-label="Session created on an older build"
                  className="shrink-0 inline-flex items-center justify-center h-[18px] min-w-[2.75rem] px-1 rounded-full bg-warn/10 text-[9px] uppercase tracking-wider text-warn/80 font-medium"
                  title={`Created on build ${sessionBuild}; current build is ${currentBuild}. Behavior may predate fixes shipped in the current build.`}
                >
                  older
                </span>
              )}
              {session.message_count > 0 && (
                <span
                  aria-hidden="true"
                  className="shrink-0 inline-flex items-center justify-center h-[18px] min-w-[1.375rem] px-1 rounded-full bg-muted-foreground/15 text-[10px] tabular-nums text-foreground/75"
                  title={`${session.message_count} messages`}
                >
                  {session.message_count}
                </span>
              )}
            </Link>
            <button
              type="button"
              aria-label="Session menu"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((v) => !v)}
              className="shrink-0 ml-1 self-center h-7 w-7 inline-flex items-center justify-center rounded-md opacity-0 group-hover:opacity-100 focus-visible:opacity-100 hover:bg-muted text-muted-foreground transition-opacity"
            >
              <MoreHorizontal className="h-3.5 w-3.5" />
            </button>
          </>
        )}
      </div>

      {menuOpen && (
        <div
          ref={menuRef}
          role="menu"
          className="absolute right-2 top-9 z-10 bg-card border border-border rounded-md min-w-[160px] py-1 text-sm"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenuOpen(false);
              setDraftTitle(session.title);
              setRenaming(true);
            }}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-muted"
          >
            <Pencil className="h-3.5 w-3.5" />
            Rename
          </button>
          {/* #313 Export submenu — flat for now (3 visible items keeps
              the menu under typical fit-on-screen). The transcript
              endpoint already supports markdown/json/docx; we just
              wire them to authenticated downloads. */}
          <ExportMenuItem
            sessionId={session.id}
            title={session.title}
            format="markdown"
            label="Export as Markdown"
            icon={<FileText className="h-3.5 w-3.5" />}
            onClose={() => setMenuOpen(false)}
          />
          <ExportMenuItem
            sessionId={session.id}
            title={session.title}
            format="json"
            label="Export as JSON"
            icon={<FileJson className="h-3.5 w-3.5" />}
            onClose={() => setMenuOpen(false)}
          />
          <ExportMenuItem
            sessionId={session.id}
            title={session.title}
            format="docx"
            label="Export as DOCX"
            icon={<Download className="h-3.5 w-3.5" />}
            onClose={() => setMenuOpen(false)}
          />
          <div className="h-px bg-border my-1" aria-hidden="true" />
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              archive.mutate(session.id);
              setMenuOpen(false);
            }}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-muted"
          >
            <Archive className="h-3.5 w-3.5" />
            Archive
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * Authenticated transcript download for one session. Fetches via
 * `apiFetch` (carries the bearer token), reads the blob, dispatches
 * a browser save with a Content-Disposition-derived filename.
 *
 * Used by the session kebab menu's three export entries (#313).
 * Each format hits the same `/transcript?format=...` endpoint —
 * markdown / json / docx — and downloads the response body.
 */
function ExportMenuItem({
  sessionId,
  title,
  format,
  label,
  icon,
  onClose,
}: {
  sessionId: string;
  title: string;
  format: "markdown" | "json" | "docx";
  label: string;
  icon: React.ReactNode;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      role="menuitem"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          const path = `/v1/chat/sessions/${encodeURIComponent(sessionId)}/transcript?format=${format}`;
          const res = await apiFetch(path);
          if (!res.ok) throw new Error(`export failed: ${res.status}`);
          const blob = await res.blob();
          const ext = format === "markdown" ? "md" : format;
          const safeTitle = title.replace(/[^a-z0-9-_]+/gi, "-") || "session";
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `${safeTitle}.${ext}`;
          a.style.display = "none";
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        } catch {
          // Non-fatal: a toast surface would be ideal but the SPA
          // doesn't have one wired here. The user can retry from
          // the menu — exports are cheap.
        } finally {
          setBusy(false);
          onClose();
        }
      }}
      className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-muted disabled:opacity-60 disabled:cursor-not-allowed"
    >
      {icon}
      {label}
    </button>
  );
}
