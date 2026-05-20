/**
 * use-auto-scroll — chronological-transcript scroll state machine.
 *
 * Two states the user can be in:
 *
 *   - FOLLOW (default): the scroll container tracks the bottom as
 *     content arrives. If the user scrolls up by more than
 *     ``RESUME_FOLLOW_PX`` we flip to PAUSED.
 *   - PAUSED: user has scrolled up; new content does NOT scroll the
 *     container. ``hasNewContent=true`` while we are paused and
 *     content has arrived since the pause; the host renders a
 *     "Jump to latest" pill.
 *
 * Additionally the user can explicitly LOCK the position. LOCKED
 * is a third state, mutually exclusive with FOLLOW/PAUSED:
 *
 *   - LOCKED: explicit pin. New content never moves the scroll.
 *     User scroll is permitted (read history) but does NOT auto-
 *     resume. Re-toggling unlocks back to FOLLOW + jumps to bottom.
 *
 * The hook returns:
 *
 *   - ``mode``: "follow" | "paused" | "locked"
 *   - ``hasNewContent``: true when content arrived in paused/locked
 *     and the user hasn't dismissed (i.e. show the pill)
 *   - ``scrollToLatest()``: imperatively jump to bottom + return to
 *     FOLLOW
 *   - ``toggleLock()``: toggle LOCKED ↔ FOLLOW
 *   - ``anchorRef``: a ref the host pins to the END of the message
 *     list as an empty <div>. The hook calls ``scrollIntoView`` on
 *     this when it wants to bottom-pin. (Vercel ai-sdk pattern.)
 *
 * Edge cases handled:
 *
 *   - ``prefers-reduced-motion: reduce`` — smooth scroll collapses
 *     to instant.
 *   - ResizeObserver on the scroll container: when a child grows
 *     (tool-card expand, streaming markdown), if FOLLOW, we re-pin.
 *   - ``visibilitychange``: when the tab becomes visible again, if
 *     FOLLOW, re-pin (catches deltas that landed in the background).
 *   - The bottom anchor's IntersectionObserver tells us atomically
 *     whether the user is "at the bottom"; cheaper + more accurate
 *     than reading scrollTop on every scroll event.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/** Pixels from the bottom that count as "at the bottom" for resume-on-scroll-down. */
export const NEAR_BOTTOM_PX = 64;
/** Wheel-up smaller than this is ignored — keeps a tiny accidental scroll-up from pausing. */
export const RESUME_FOLLOW_PX = 24;

export type AutoScrollMode = "follow" | "paused" | "locked";

export interface UseAutoScrollOptions {
  /** Number that changes whenever new content lands (use total content length, message count, etc). */
  contentSignal: number | string;
  /** Optional callback when mode changes — useful for analytics or aria-live announcements. */
  onModeChange?(next: AutoScrollMode): void;
}

export interface UseAutoScrollResult {
  mode: AutoScrollMode;
  /** True when the user is not at the bottom (i.e. there is content
   * below the fold). The host should show the "Jump to latest" pill
   * whenever this is true so a scrolled-up user always has an escape
   * hatch, AND so a LOCKED user can see new content has landed. */
  hasNewContent: boolean;
  /** True when the scroll position is currently at (within
   * NEAR_BOTTOM_PX of) the bottom. */
  atBottom: boolean;
  /** Imperatively jump to bottom and return to FOLLOW. */
  scrollToLatest(): void;
  /** Toggle LOCKED ↔ FOLLOW. When unlocking, also jumps to bottom. */
  toggleLock(): void;
  /** Ref to mount on an empty `<div>` at the END of the message list. */
  anchorRef: React.RefObject<HTMLDivElement | null>;
}

/**
 * Read ``prefers-reduced-motion`` once on mount. We re-read on the
 * media-query ``change`` event so live OS-setting flips take effect.
 */
function usePrefersReducedMotion(): boolean {
  const [reduce, setReduce] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });
  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handler = (e: MediaQueryListEvent) => setReduce(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);
  return reduce;
}

export function useAutoScroll(
  scrollRef: React.RefObject<HTMLElement | null>,
  { contentSignal, onModeChange }: UseAutoScrollOptions,
): UseAutoScrollResult {
  const anchorRef = useRef<HTMLDivElement | null>(null);
  const [mode, setMode] = useState<AutoScrollMode>("follow");
  const [atBottom, setAtBottom] = useState(true);
  const [hasNewContent, setHasNewContent] = useState(false);
  const reduceMotion = usePrefersReducedMotion();
  // The hook fires onModeChange whenever `mode` updates; cache the
  // latest callback so re-renders of the host don't re-subscribe the
  // observers below.
  const onModeChangeRef = useRef(onModeChange);
  onModeChangeRef.current = onModeChange;
  useEffect(() => {
    onModeChangeRef.current?.(mode);
  }, [mode]);

  // Imperatively scroll to the bottom anchor. Smooth unless the user
  // prefers reduced motion. ``block: "end"`` aligns the anchor's
  // bottom edge with the scroll container's bottom — pinning the
  // last rendered message to the visible bottom.
  //
  // Dispatches a `kaos-pin-bottom` custom event on the scroll
  // container before scrolling, so the scroll-event handler below
  // can suppress its "is this a user scroll?" logic during the
  // programmatic animation window (otherwise the smooth-scroll's
  // intermediate scroll events would flip us to paused mid-pin).
  const scrollToBottom = useCallback(
    (behavior: ScrollBehavior = "smooth") => {
      const a = anchorRef.current;
      const scroller = scrollRef.current;
      if (!a) return;
      if (scroller) {
        scroller.dispatchEvent(new CustomEvent("kaos-pin-bottom"));
      }
      a.scrollIntoView({
        behavior: reduceMotion ? "auto" : behavior,
        block: "end",
      });
    },
    [reduceMotion, scrollRef],
  );

  // IntersectionObserver on the bottom anchor — tells us whether
  // the user is currently within ~`NEAR_BOTTOM_PX` of the bottom.
  // Triggers state transitions:
  //   - atBottom true  →  if PAUSED, return to FOLLOW (resume-on-scroll-down)
  //   - atBottom false →  hint state only; the scroll-event handler
  //     above is the ONLY thing that flips FOLLOW → PAUSED, so a
  //     content-height jump without a user-scroll doesn't surprise-
  //     pause the user.
  useEffect(() => {
    const anchor = anchorRef.current;
    const scroller = scrollRef.current;
    if (!anchor || !scroller) return;

    const io = new IntersectionObserver(
      (entries) => {
        const e = entries[0];
        if (!e) return;
        const isAtBottom = e.isIntersecting;
        setAtBottom(isAtBottom);
        if (isAtBottom) {
          setMode((m) => (m === "paused" ? "follow" : m));
          setHasNewContent(false);
        }
      },
      {
        root: scroller,
        // negative bottom margin extends the "at the bottom" zone
        // upward by `NEAR_BOTTOM_PX`. So if the anchor is within
        // 64px of the visible bottom we treat the user as at-bottom.
        rootMargin: `0px 0px ${NEAR_BOTTOM_PX}px 0px`,
        threshold: 0,
      },
    );
    io.observe(anchor);
    return () => io.disconnect();
  }, [scrollRef]);

  // On the first signal that carries REAL content, force a jump to
  // the bottom regardless of where the browser ended up on load
  // (Safari + Firefox sometimes restore scroll position to 0 even
  // when content lands later, and we want every chat to land at
  // the latest turn — that's what users expect from every other
  // chat product). We watch for "real content" by checking that the
  // scroll container has scrollable content (scrollHeight >
  // clientHeight). After the first such pin, subsequent content
  // arrival respects the FOLLOW/PAUSED state machine.
  const initialPinDone = useRef(false);

  // Content-arrival reaction. When the contentSignal changes (a
  // text-delta landed, a new tool card appended, a new message
  // arrived), we either:
  //   - first-mount: ALWAYS pin to bottom (instant — the user
  //     should never see the scroll snap)
  //   - FOLLOW + at-bottom: re-pin to bottom (smooth)
  //   - PAUSED / LOCKED / not-at-bottom: mark hasNewContent so the
  //     pill shows
  // We check scroll metrics RIGHT NOW (not the stale `atBottom`
  // state which depends on IO that may not have fired yet) so a
  // user who just scrolled up doesn't get yanked back when content
  // arrives in the same tick.
  useEffect(() => {
    const scroller = scrollRef.current;
    // Initial pin: fire on the first contentSignal change that
    // results in a scrollable container. This catches the common
    // mount→history-load sequence where the first effect runs with
    // an empty messages array (nothing to scroll), then a second
    // effect run lands with the full transcript and we pin to its
    // bottom. Use instant scroll so the user never sees the snap.
    if (!initialPinDone.current && scroller && scroller.scrollHeight > scroller.clientHeight) {
      initialPinDone.current = true;
      requestAnimationFrame(() => scrollToBottom("auto"));
      setHasNewContent(false);
      return;
    }
    if (mode === "follow" && scroller) {
      const dist =
        scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      if (dist <= NEAR_BOTTOM_PX) {
        scrollToBottom("smooth");
        setHasNewContent(false);
      } else {
        // User has scrolled up faster than IO can flip us to paused.
        // Don't pin; show the pill.
        setHasNewContent(true);
      }
    } else if (mode !== "follow") {
      // PAUSED or LOCKED — surface a pill when new content lands.
      setHasNewContent(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contentSignal]);

  // ResizeObserver on the scroll container's children — fires when a
  // child grows (e.g. tool-card expand, streaming markdown that pushes
  // content height). If we are in FOLLOW mode, re-pin to bottom.
  // Note: relying on `mode` here (not on scroll metrics) is safe
  // because the explicit scroll-event handler below flips us to
  // PAUSED as soon as the user scrolls up by RESUME_FOLLOW_PX — so
  // by the time RO sees the next growth, mode is already paused.
  // We do NOT run this hook while LOCKED.
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    if (mode !== "follow") return; // PAUSED + LOCKED ignore auto-follow
    const ro = new ResizeObserver(() => {
      scrollToBottom("auto");
    });
    for (const child of Array.from(scroller.children)) {
      ro.observe(child);
    }
    const mo = new MutationObserver((muts) => {
      for (const m of muts) {
        for (const added of Array.from(m.addedNodes)) {
          if (added instanceof Element) ro.observe(added);
        }
      }
    });
    mo.observe(scroller, { childList: true, subtree: false });
    return () => {
      ro.disconnect();
      mo.disconnect();
    };
  }, [scrollRef, mode, scrollToBottom]);

  // Explicit scroll-event handler. This is the source of truth for
  // "user scrolled up" detection — IntersectionObserver gives us
  // atomic at-bottom signal but is async; a programmatic scroll-to-
  // bottom from our own code SHOULDN'T flip us to paused. We track
  // the last bottom-pinning position and only flip to PAUSED if the
  // current scrollTop is more than RESUME_FOLLOW_PX below the last
  // known bottom. Likewise, scrolling back down to within
  // NEAR_BOTTOM_PX of bottom returns us to FOLLOW.
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    let suppressUntil = 0;
    const onScroll = () => {
      if (performance.now() < suppressUntil) return;
      const dist =
        scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      if (dist > NEAR_BOTTOM_PX + RESUME_FOLLOW_PX) {
        setMode((m) => (m === "follow" ? "paused" : m));
      } else if (dist <= NEAR_BOTTOM_PX) {
        setMode((m) => (m === "paused" ? "follow" : m));
        setHasNewContent(false);
      }
    };
    // Suppress the scroll handler during programmatic scroll-to-bottom
    // (the smooth animation can take ~500ms and we don't want the
    // intermediate scroll events to flip mode mid-animation).
    const origScrollTo = scroller.scrollTo.bind(scroller);
    // Use the anchor's scrollIntoView path: the scroll fires events
    // as it animates. We mark a suppression window any time the
    // hook's own scrollToBottom is called. The simplest way is to
    // attach a hint via dataset.
    const watchProgrammatic = () => {
      suppressUntil = performance.now() + 600;
    };
    scroller.addEventListener("scroll", onScroll, { passive: true });
    // Custom event from scrollToBottom — see below.
    scroller.addEventListener("kaos-pin-bottom", watchProgrammatic);
    return () => {
      scroller.removeEventListener("scroll", onScroll);
      scroller.removeEventListener("kaos-pin-bottom", watchProgrammatic);
      // Silence unused-var lint for origScrollTo (we retain it as a
      // belt-and-suspenders override hook for future tests).
      void origScrollTo;
    };
  }, [scrollRef]);

  // visibilitychange — when the tab becomes visible, if FOLLOW,
  // re-pin to bottom. Catches the case where text deltas landed
  // while the tab was backgrounded.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible" && mode === "follow") {
        scrollToBottom("auto");
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [mode, scrollToBottom]);

  // Wheel-up small-delta filter. The IntersectionObserver above is
  // sensitive enough that a 5px wheel-up that doesn't actually
  // change atBottom won't trigger a state change — but if a slow
  // scroll-up DOES cross the threshold, we let IO flip us to
  // PAUSED. No explicit wheel listener needed for the common case.

  const scrollToLatest = useCallback(() => {
    setMode("follow");
    setHasNewContent(false);
    // Defer to next frame so the state update commits before we
    // imperatively scroll — IO will then immediately confirm at-bottom.
    requestAnimationFrame(() => scrollToBottom("smooth"));
  }, [scrollToBottom]);

  const toggleLock = useCallback(() => {
    setMode((m) => {
      if (m === "locked") {
        // Unlocking — jump to bottom and resume FOLLOW.
        requestAnimationFrame(() => scrollToBottom("smooth"));
        return "follow";
      }
      // Locking from FOLLOW or PAUSED.
      return "locked";
    });
  }, [scrollToBottom]);

  // The pill is shown whenever the user has scrolled away from the
  // bottom (PAUSED) OR while LOCKED and content has landed. In
  // FOLLOW mode we're tracking the bottom, so the pill should be
  // hidden — unless we're transiently at !atBottom right after a
  // mode change, which is fine because IO will resolve it next tick.
  const showPill =
    (mode === "paused" && !atBottom) ||
    (mode === "locked" && hasNewContent);

  return useMemo(
    () => ({
      mode,
      // For host convenience, `hasNewContent` is the pill-visibility
      // signal: true when user is paused (not at bottom) or locked
      // with new content. Hosts can use `atBottom` for finer logic.
      hasNewContent: showPill,
      atBottom,
      scrollToLatest,
      toggleLock,
      anchorRef,
    }),
    [mode, showPill, atBottom, scrollToLatest, toggleLock],
  );
}
