import { Link } from "@tanstack/react-router";
import { Archive, MoreHorizontal } from "lucide-react";
import { useState } from "react";

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
 * - Right-aligned MoreHorizontal trigger reveals the menu on hover.
 */
export function SessionListItem({ session, active }: Props) {
  const [open, setOpen] = useState(false);
  const archive = useArchiveSession();

  return (
    <div className="group relative">
      {active && (
        <span
          aria-hidden
          className="absolute left-0 top-1.5 bottom-1.5 w-[2px] bg-accent rounded-full"
        />
      )}
      <Link
        to="/sessions/$id"
        params={{ id: session.id }}
        className={
          "flex items-center h-9 px-3 rounded-md text-sm transition-colors " +
          (active ? "bg-muted text-foreground" : "text-foreground hover:bg-muted")
        }
        title={session.title}
      >
        <span className="truncate flex-1 pr-2">{session.title || "Untitled"}</span>
        <button
          type="button"
          aria-label="Session menu"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setOpen((v) => !v);
          }}
          className={
            "opacity-0 group-hover:opacity-100 focus-visible:opacity-100 " +
            "p-1 rounded hover:bg-background -mr-1 transition-opacity"
          }
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
      </Link>

      {open && (
        <div
          role="menu"
          className="absolute right-2 top-9 z-10 bg-card border border-border rounded-md min-w-[140px] py-1 text-sm"
          onMouseLeave={() => setOpen(false)}
        >
          <button
            type="button"
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
