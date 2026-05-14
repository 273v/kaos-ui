import { LogOut, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useEffect, useState } from "react";

import { useAuth } from "@/auth/context";
import { NewChatButton } from "@/components/sessions/NewChatButton";
import { SessionList } from "@/components/sessions/SessionList";

const COLLAPSE_KEY = "kaos-chat-example.sidebar.collapsed";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Left rail per UX-LANGUAGE.md § 4.1:
 *  - 264 px expanded, 56 px collapsed
 *  - bg-secondary, hairline right border
 *  - Cmd/Ctrl+B toggles collapse; state persists in localStorage
 *  - Serif app name + New-chat button stacked at top
 *  - Recents below
 *  - Avatar/logout at the bottom
 */
export function Sidebar() {
  const auth = useAuth();
  const [collapsed, setCollapsed] = useState<boolean>(() => readCollapsed());

  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        setCollapsed((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <aside
      className={
        "flex flex-col h-full border-r border-border bg-secondary " +
        "transition-[width] duration-150 " +
        (collapsed ? "w-14" : "w-[264px]")
      }
    >
      <div className="flex items-center justify-between p-3">
        {!collapsed && (
          <span className="text-lg font-serif font-light tracking-tight">Single-User Chat</span>
        )}
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          className="p-1.5 rounded hover:bg-muted text-muted-foreground"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand (⌘B)" : "Collapse (⌘B)"}
        >
          {collapsed ? (
            <PanelLeftOpen className="h-4 w-4" />
          ) : (
            <PanelLeftClose className="h-4 w-4" />
          )}
        </button>
      </div>

      {!collapsed && (
        <>
          <div className="px-3 pb-2">
            <NewChatButton />
          </div>

          <div className="flex-1 overflow-y-auto pt-2">
            <SessionList />
          </div>

          <div className="border-t border-border p-2">
            <button
              type="button"
              onClick={() => auth.logout()}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <LogOut className="h-3.5 w-3.5" />
              Sign out
            </button>
          </div>
        </>
      )}
    </aside>
  );
}
