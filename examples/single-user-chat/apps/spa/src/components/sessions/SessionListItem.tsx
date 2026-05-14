import { Link } from "@tanstack/react-router";
import { Archive, MoreHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useArchiveSession } from "@/hooks/use-archive-session";
import type { SessionSummary } from "@/lib/api-types";

interface Props {
  session: SessionSummary;
  active: boolean;
}

/**
 * Single sidebar row.
 * - h-9 height per UX-LANGUAGE § 4.6
 * - hover: bg-muted; active: bg-muted + 2px amber left-edge stripe
 * - Menu trigger lives OUTSIDE the link (LOW #2 fix — pre-fix the
 *   <button> was nested inside <a>, which lets clicks bubble back
 *   to the link and also confuses screen readers).
 */
export function SessionListItem({ session, active }: Props) {
  const [open, setOpen] = useState(false);
  const archive = useArchiveSession();
  const menuRef = useRef<HTMLDivElement | null>(null);

  // Click-outside / Escape closes the menu.
  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="group relative">
      {active && (
        <span
          aria-hidden
          className="absolute left-0 top-1.5 bottom-1.5 w-[2px] bg-accent rounded-full"
        />
      )}
      <div className="flex items-stretch">
        <Link
          to="/sessions/$id"
          params={{ id: session.id }}
          className={
            "flex items-center h-9 px-3 rounded-md text-sm transition-colors flex-1 min-w-0 " +
            (active ? "bg-muted text-foreground" : "text-foreground hover:bg-muted")
          }
          title={session.title}
        >
          <span className="truncate">{session.title || "Untitled"}</span>
        </Link>
        <button
          type="button"
          aria-label="Session menu"
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className={
            "shrink-0 ml-1 self-center h-7 w-7 inline-flex items-center justify-center rounded-md " +
            "opacity-0 group-hover:opacity-100 focus-visible:opacity-100 " +
            "hover:bg-muted text-muted-foreground transition-opacity"
          }
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
      </div>

      {open && (
        <div
          ref={menuRef}
          role="menu"
          className="absolute right-2 top-9 z-10 bg-card border border-border rounded-md min-w-[140px] py-1 text-sm"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              archive.mutate(session.id);
              setOpen(false);
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
