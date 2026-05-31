# Chat turn-lifecycle redesign — eliminating the follow-up-send race

Status: design proposal
Scope: `examples/single-user-chat` SPA + FastAPI backend, and the shared
`packages/kaos-ui-react` send hook.
Audience: implementer of the turn-lifecycle rework.

This document specifies a structural redesign of the chat turn lifecycle
so that the follow-up-message "flash and disappear" failure becomes
*impossible by construction*, not merely guarded against. The root cause
is already confirmed; this doc does not re-litigate it. It proposes one
source of truth for transcript state, a server-authoritative turn state
machine, the specific 409-window and refetch-wipe fixes, a file-anchored
minimal change list, and a deterministic regression test.

---

## 1. Root cause, and why band-aids keep failing

### 1.1 The confirmed mechanism

A follow-up message (2nd+ turn in a session) fails ~50% of the time
because three independent "turn is done" signals are never coordinated,
and two independent sources of truth for the transcript fight each other:

1. **Lock outlives the stream.** `POST /v1/chat/sessions/{id}/messages`
   acquires a per-session `asyncio.Lock`
   (`backend/app/routers/chat.py:554-555`) and 409s any concurrent POST
   (`chat.py:537-553`). The lock is released only inside `_do_persist`'s
   `finally:` (`chat.py:744`). `_do_persist` is a Starlette
   `BackgroundTask` (`chat.py:1091`) that runs *after* the SSE response
   body is fully sent, and it does heavy work first:
   `persist_canonical_turn` (an upstream POST, `chat.py:690`),
   `persist_turn_completion` (memory persist + title heuristic + history
   fetch, `chat.py:702`), then `run_log.mark_done` (`chat.py:731`). So
   the session stays "running" for hundreds of ms to seconds *after the
   client already saw the SSE terminal event*.

2. **Client thinks it's free the instant the stream ends.** The
   `turn_summary` event sets `pending: false`
   (`packages/kaos-ui-react/src/lib/event-handler.ts:357`). The composer
   re-enables (`_auth.sessions.$id.tsx:254` checks
   `stream.state.pending`). If the user sends inside the
   lock-still-held window → backend returns **409** →
   `readSseStream` throws (`streaming.ts:75`) → the hook's `catch`
   injects a synthetic `run_error` banner
   (`use-send-message.ts:356-362`) → `finally` sets
   `pendingRef=false` (`use-send-message.ts:365`).

3. **A racing history refetch wipes the optimistic state.** On the
   turn-done edge the route invalidates history *immediately and again
   at +1200ms* (`_auth.sessions.$id.tsx:227-242`, B8 / UX-A1).
   `initialMessages = useMemo(..., [history.data])`
   (`_auth.sessions.$id.tsx:102-163`) produces a fresh array reference
   on each refetch. That new reference flows into the send hook's reset
   effect (deps `[opts.sessionId, opts.initialMessages]`,
   `use-send-message.ts:166-200`), which calls
   `setState({ ...initialState, messages: serverHistory })` whenever
   `pendingRef.current` is false. After the 409 flips `pendingRef`
   false, the +1200ms refetch resolves and the reset effect **wipes both
   the optimistic user message and the error banner** → "flash and
   disappear, no feedback."

The 50% is a pure race: BackgroundTask lock-release completion vs. how
fast the user hits Enter.

### 1.2 Why band-aids keep failing

The send hook already carries: `pendingRef`, `pendingKindRef` with a
`setTimeout(0)` preemption dance, `attachedRunIdRef`, FIX-9, B1.2 (lock
release on the 409 path), B8 + UX-A1 (+1200ms invalidate), and the
reset-effect's "keep `attachedRunIdRef` across same-session refetch" P0
note. Tasks #459/#351 were prior attempts.

Every one of these is a *timing patch on a system whose timings are
unspecified*. They fail because the architecture has:

- **Two sources of truth for the transcript** — the optimistic reducer
  state inside `useSendMessage` *and* the TanStack-Query `history`
  cache, reconciled only by an `invalidate → refetch → useMemo → reset
  effect` chain whose ordering relative to the live stream is undefined.
- **Three uncoordinated "turn done" signals** — the SSE terminal event
  (`turn_summary`), the session-lock release (in the BackgroundTask),
  and the active-pointer flip (`run_log.mark_done`). The client trusts
  signal #1; the server gates on signal #2; resume keys off signal #3.
  Nothing guarantees #1 ≤ #2 ≤ #3 in wall-clock time.

You cannot win a race by adding more `setTimeout`s to one side. The fix
is to remove the race: make "free for the next turn" a *server fact the
client can observe*, and make the transcript a *single store* that a
refetch reconciles into without clobbering in-flight optimistic rows.

---

## 2. Target architecture

### 2.1 One source of truth for transcript state

**Decision: the `useSendMessage` reducer (`TranscriptState`) is the sole
render source for the transcript. The history query becomes a *hydration
seed and a background reconciler*, never a competing renderer.**

This mirrors how mature clients structure it. assistant-ui keeps a single
`ThreadRuntime` store whose `AssistantMessageAccumulator` merges streamed
chunks into message state keyed by message id, so "the UI receives a
consistent view of the message even when tokens arrive out of order"
([assistant-ui ThreadRuntime / assistant-stream][au]). The Vercel AI SDK
`useChat` likewise owns one `messages` array with per-message `id` and a
single `status` field; the server stream merges *into* it by id rather
than replacing it ([AI SDK useChat][aisdk-msg]).

Concretely:

- Every transcript row gets a **stable client id** and a **client-origin
  marker**. `pushUserAndAssistantPlaceholder` already mints `newId()`
  for both rows (`event-handler.ts:557-583`). Add a
  `clientKey` (the idempotency key, see §3) on the user row and an
  `origin: "optimistic" | "server"` tag.
- The reset effect **never replaces rows that are optimistic or
  streaming**. Hydration only *fills in* server rows the reducer doesn't
  already have (matched by `clientKey` for user rows, by ordinal for
  historical rows). This is the "merge by id, don't replace the array"
  rule from both assistant-ui and AI SDK.

### 2.2 Server-authoritative turn lifecycle state machine

Introduce an explicit per-session run state, persisted in the existing
`runs/active.json` pointer (`backend/app/services/run_log.py`), with
these states:

```
            POST /messages (lock acquired, run_log opened)
   idle ───────────────────────────────────────────────► streaming
     ▲                                                        │
     │                                                        │ last SSE frame sent
     │                                                        ▼
     │                                                    draining        ← NEW state
     │   persist + mark_done complete                         │             (stream done,
     └────────────────────────────────────────────────── ◄───┘              persist running)
```

- **idle** — no lock held, no active pointer (or pointer `status:"done"`).
  A POST is accepted immediately.
- **streaming** — lock held, SSE body in flight. A concurrent POST is
  *queued by the client* (see §3b), never silently dropped.
- **draining** (new) — the SSE terminal frame has been sent, but persist
  is still running. **The lock is already released here.** A POST in this
  window is accepted; persist for the prior turn finishes independently.

The key invariant: **the lock lifetime equals the SSE stream lifetime,
NOT the persist lifetime.** Persist is decoupled from "session free."

Client-side, the hook tracks a matching `TurnStatus`:

```
idle → sending(optimistic row added) → streaming → settling → idle
                                          │
                                          └─► error (terminal, NOT wiped by refetch)
```

`settling` is the client mirror of server `draining`: the SSE terminal
event arrived, the reducer has the final text, and we may issue the next
send immediately. The next user message in `settling` is allowed because
the server lock is already free.

### 2.3 How the operations compose without races

- **send** — mint a `clientKey` (UUID). Optimistically push user +
  assistant-placeholder rows tagged `origin:"optimistic"`,
  `clientKey`. POST with `Idempotency-Key: <clientKey>`.
- **optimistic-add** — lives only in the reducer. Never written to the
  history query cache, so a history refetch cannot clobber it
  ([tkdodo: derive UI from pending mutations, don't write the cache][tk]).
- **reconcile** — when the history query resolves, the reducer merges:
  for each server row, if a reducer row with the same `clientKey`
  (user) exists, mark it `origin:"server"` and keep the streamed
  assistant content as authoritative until the server text is present;
  otherwise append. Rows that are `streaming` or still-optimistic are
  never removed. (This is "merge by id," not "replace array.")
- **concurrent follow-up** — if `serverTurnStatus === streaming`, the
  send is **enqueued** and auto-flushed when the stream ends (Claude
  Code / ChatGPT queue model, [Claude Code message-queue issues][cc]).
  If `settling`/`idle`, it fires immediately because the lock is free.
- **resume** — unchanged transport (`GET /runs/{run_id}/events`,
  `backend/app/routers/runs.py:80`), but now gated on the *same*
  `serverTurnStatus` the send path reads, so resume and send cannot both
  claim the run. This is the AI SDK model: on mount, GET the active
  stream; resume only if the server says one is live; clear on finish
  ([AI SDK resume streams][aisdk]).
- **error** — a `run_error` row is `origin:"optimistic"` + `terminal:
  true`. The reconciler treats terminal error rows like streaming rows:
  never removed by a refetch. The user sees the failure and can retry.

---

## 3. The 409 window — options and recommendation

The 409 fires because a follow-up POST lands while the lock is held for a
prior turn whose *stream already ended*. Four options:

**(a) Release the lock at stream-end; move persist off the lock.**
Release `_session_lock` in the SSE generator's `finally:`
(`chat.py:1024-1076`) the moment the body is fully yielded, and let
`_do_persist` run with no lock held. The "draining" state from §2.2.
*Pro:* eliminates the window at the source — the lock now equals the
stream, exactly as the doc's invariant requires. *Con:* persist for turn
N can now overlap the *stream* of turn N+1. Both write SessionMemory via
the upstream `persist_canonical_turn` / `persist_turn_completion`. This
must be made safe (see below).

**(b) Client queues follow-ups until "session free."** Hold the second
send in a client queue while `serverTurnStatus === streaming`; flush on
terminal event. *Pro:* matches Claude Code / ChatGPT UX; never shows a
409. *Con:* alone, it doesn't fix the window because the client's notion
of "free" (SSE terminal) still precedes the lock release. Only safe when
combined with (a).

**(c) 409 → auto-resume/auto-retry.** On 409, auto-open the resume
stream or retry after backoff. *Pro:* no code change to the lock. *Con:*
pure band-aid; reintroduces timing guesswork; the resume stream for a
*just-finished* run races `mark_done`. This is exactly the class of
patch we are removing.

**(d) Idempotency key (Stripe-style).** Client mints a UUID per logical
send and passes `Idempotency-Key`; the server dedupes so a retried or
double-fired POST returns the same run instead of starting a second one
([Stripe idempotency][stripe]). *Pro:* makes retries and double-submits
*safe* regardless of timing. *Con:* doesn't by itself release the lock
sooner, so it doesn't close the window alone.

### Recommendation: **(a) primary + (d) secondary, with (b) as the UX layer.**

- **(a)** is the structural fix and the only one that makes the race
  impossible: once the lock lifetime == stream lifetime, a follow-up
  that starts after the SSE terminal event *always* finds the lock free.
  Adopt the "draining" state so persist runs lock-free.
- To make (a) safe against turn-N persist overlapping turn-N+1, the
  canonical-turn write must be **per-turn idempotent**. Key the upstream
  `persist_canonical_turn` write on `run_id` (already unique per turn,
  `chat.py:601`) so a slow turn-N persist cannot corrupt turn-N+1's
  memory append. This is where **(d)** pays for itself: the
  `Idempotency-Key` is the `run_id`/`clientKey`, and the persist path
  becomes a keyed upsert.
- **(b)** is the user-facing behavior: with the lock released at
  stream-end the *common* follow-up never 409s, and for the genuinely
  concurrent case (two tabs, or typing during streaming) the client
  queues rather than dropping — so the user never sees a silent failure.

The legacy soft-409 on `runs/active.json` (`chat.py:569-594`) stays only
as a cross-process / post-restart guard, but with (a) it no longer fires
on the normal follow-up path because the pointer flips to a terminal
state as part of `mark_done`, and the *lock* (not the pointer) is what
the fast path consults.

---

## 4. The reset-on-refetch wipe

The wipe is `use-send-message.ts:166-200`: the reset effect runs on every
new `initialMessages` reference and, when `pendingRef.current` is false,
calls `setState({ ...initialState, messages: opts.initialMessages })`,
destroying optimistic + error rows.

**Fix: stop reconciling optimistic state from a racing history refetch.
Two coordinated changes:**

1. **Split hydration from reset.** The effect must do exactly one of:
   - *Reset* — only when `opts.sessionId` actually changed (navigation).
     This may legitimately blow away state and abort the stream.
   - *Reconcile* — same-session `initialMessages` change. Merge server
     rows into the reducer by `clientKey`/ordinal (§2.1). **Never**
     `setState(initialState + serverHistory)` for a same-session
     refetch. Preserve any reducer row that is `streaming`, still
     `origin:"optimistic"`, or a terminal `run_error`.

2. **Don't fire the racing refetch in the first place.** Replace the
   B8/UX-A1 double-invalidate (`_auth.sessions.$id.tsx:227-242`) with the
   tkdodo guard: only invalidate `history` when this turn is the last
   one settling, and *never* invalidate `history` while
   `serverTurnStatus !== idle`
   ([tkdodo concurrent optimistic updates][tk]). The session-`meta` and
   sidebar-`list` invalidations (for title/`message_count`) can stay —
   they don't feed `initialMessages` and so can't wipe the transcript.
   The +1200ms title race is better solved by having the backend emit a
   `title_updated` SSE frame (or include the final title in
   `turn_summary`) so the client updates the header from the stream it
   already trusts, instead of polling `meta` on a timer.

Net effect: the only path that can change transcript rows during/after a
turn is the reducer. The history query can refetch as often as it likes;
it can only *fill in* server-confirmed rows, never delete optimistic or
streaming ones. This is the single-source-of-truth invariant from §2.1
made enforceable.

---

## 5. Concrete, minimal change list (file:line anchored)

### `backend/app/routers/chat.py`

- **Release the lock at stream-end (option a).** Move
  `_release_session_lock()` out of `_do_persist`'s `finally:`
  (`chat.py:744`) and into the `event_generator`'s `finally:` block
  (after `persist_snapshot["captured"] = True`, around
  `chat.py:1041-1076`). Keep `_release_session_lock` idempotent so the
  early-409 path (`chat.py:578`) and the new stream-end release don't
  double-release. After this, `_do_persist` runs lock-free.
- **Make canonical persist per-turn idempotent (supports a + d).** Thread
  `run_id` into `persist_canonical_turn` (`chat.py:690`) and the upstream
  `/memory/messages/turn` write so a slow turn-N persist that overlaps
  turn-N+1's stream is a keyed upsert, not a blind append.
- **Accept `Idempotency-Key` (option d).** In `send_message`
  (`chat.py:398-407`) read the `Idempotency-Key` header (fall back to a
  body field). If a run with that key is already `streaming`/recently
  `done` for this session, return its `run_id` (and, for an in-flight
  one, point at the resume endpoint) instead of starting a new run. Use
  `run_id` as the stored key.
- **Stream the title.** When `is_first_turn` (`chat.py:499`) and a title
  is derived, emit a `title_updated` SSE frame from `event_generator`
  (or add `title` to the `turn_summary` payload) so the client doesn't
  need the +1200ms `meta` poll.
- The two 409 raises (`chat.py:537-553`, `chat.py:579-594`) stay, but the
  hard 409 (`is_session_running`) now only fires for genuinely concurrent
  streaming, and the client queues around it (§3b) so it isn't
  user-visible.

### `packages/kaos-ui-react/src/hooks/use-send-message.ts`

- **Add `clientKey` + `origin` + a send queue.** Mint a UUID per `send()`
  (`use-send-message.ts:297`), tag the optimistic rows, and pass
  `Idempotency-Key` on the POST (`use-send-message.ts:328-341`).
- **Split the reset effect (fixes §4.1).** In the effect at
  `use-send-message.ts:166-200`, branch hard on `sessionChanged`:
  - `sessionChanged` → current reset behavior (abort + `setState`).
  - same-session → **reconcile-merge only**; never
    `setState(initialState + serverHistory)`; preserve `streaming` /
    `origin:"optimistic"` / terminal-`run_error` rows.
- **Queue concurrent sends (option b).** In `send()`
  (`use-send-message.ts:299-315`), when `serverTurnStatus === streaming`,
  push the message onto a queue and return; flush the queue when the
  reducer reaches `settling`/`idle`. Delete the `pendingKindRef`
  `setTimeout(0)` preemption dance (`use-send-message.ts:308-313`) — it
  exists only to paper over the dropped-send symptom this removes.
- **Track `serverTurnStatus` from the active-run pointer + stream end**,
  so send/resume read one status instead of the `pendingRef` /
  `attachedRunIdRef` / `pendingKindRef` trio.

### `examples/single-user-chat/apps/spa/src/routes/_auth.sessions.$id.tsx`

- **Replace the B8/UX-A1 double-invalidate** (`_auth.sessions.$id.tsx:227-242`):
  - Drop the `setTimeout(invalidate, 1200)` entirely.
  - Guard the `history` invalidation behind "session idle and no queued
    send" (tkdodo `isMutating`-style guard). Keep `meta` + `sessions`
    invalidations.
- **Consume the streamed `title_updated`** (or `turn_summary.title`) to
  update the header instead of polling `meta`.
- `initialMessages` `useMemo` (`_auth.sessions.$id.tsx:102-163`) is now a
  pure *seed* for first hydration and a reconcile input — its referential
  churn is harmless because the hook no longer resets from it
  same-session.

### `examples/single-user-chat/apps/spa/src/hooks/use-session-messages.ts`

- Consider `refetchOnWindowFocus: false` (currently `true`,
  `use-session-messages.ts:42`) for the active session, or keep it but
  rely on the §4.1 reconcile-merge to make focus-refetch non-destructive.
  With the split reset effect, focus refetch is safe either way; turning
  it off simply removes an unnecessary refetch.

---

## 6. Deterministic regression test

The bug is a wall-clock race, so the test must make the race
*deterministic* by controlling the two clocks: the lock-release timing
and the persist timing.

### 6.1 Backend (pytest, ASGITransport) — the lock window is closed

Goal: prove a follow-up POST issued *after* the first stream's terminal
event, but *while persist is still running*, succeeds (no 409).

1. Patch `persist_turn_completion` (and `persist_canonical_turn`) with an
   `asyncio.Event` gate so the BackgroundTask blocks until the test
   releases it — simulating a slow persist deterministically.
2. POST turn 1; drain the SSE response fully (consume to the terminal
   `turn_summary`/EOF). Do **not** release the persist gate yet.
3. Immediately POST turn 2 to the same session.
4. **Assert turn 2 returns 200 and an SSE stream** (pre-fix: 409). This
   is the load-bearing assertion — it can only pass if the lock was
   released at stream-end, not in `_do_persist`.
5. Release the persist gate; assert both turns' canonical writes landed
   exactly once each (idempotency: keyed on `run_id`, no double-append,
   no cross-turn corruption).

A second backend test asserts the **idempotency key**: two POSTs with the
same `Idempotency-Key` yield the same `run_id` and a single memory
append.

### 6.2 Client (Vitest + msw) — the refetch can't wipe optimistic state

Goal: prove a history refetch resolving after a turn cannot delete the
optimistic user row or an error row.

1. Render the hook with a controllable msw `GET .../messages` whose
   resolution the test gates (resolve on command).
2. `send("first")`, stream a `turn_summary` so the reducer reaches
   `settling`.
3. `send("second")` while the gated refetch for turn 1 is still pending.
4. Resolve the history refetch with *only* turn 1's server rows (the
   realistic racing payload that triggered the wipe).
5. **Assert the reducer still contains the optimistic "second" user row
   and its streaming assistant placeholder** (pre-fix: both gone).
6. Variant: force the second POST to 409 (msw), assert the `run_error`
   row survives the subsequent history refetch.

These tests are deterministic because every timing edge (persist
completion, history-refetch resolution) is an explicitly released gate,
not a `sleep`/`setTimeout`. No flake surface.

A property test already exists for replay/live equivalence
(`event-handler.replay.test.ts`, referenced in `use-send-message.ts:19`);
extend it to assert the reconcile-merge is idempotent: merging the same
server history twice equals merging once.

---

## 7. Citations

- **Vercel AI SDK `useChat` resume streams** — GET `/api/chat/[id]/stream`
  on mount, `activeStreamId` persisted server-side and cleared in
  `onFinish`, single `messages` array merged by message `id` + a `status`
  field. The model for "server owns the active-run fact; client observes
  it; merge into one store."
  [AI SDK UI: Chatbot Resume Streams][aisdk] ·
  [AI SDK useChat message id/status][aisdk-msg]
- **assistant-ui `ThreadRuntime` / assistant-stream** — single thread
  store; "running"/"complete"/"incomplete" message status; an
  accumulator merges streamed chunks by id so the UI stays consistent
  even with out-of-order tokens. The single-source-of-truth + merge-by-id
  model. [assistant-ui ThreadRuntime][au]
- **ChatGPT / Claude Code consecutive-send behavior** — messages typed
  while a turn runs are *queued* and flushed at a pause, not dropped or
  hard-rejected. Basis for §3(b) client queue.
  [Claude Code message-queue design discussion][cc]
- **TanStack Query concurrent optimistic updates** — cancel queries in
  `onMutate`; *don't* invalidate after every mutation; guard invalidation
  on `isMutating(...) === 1`; prefer deriving UI from pending-mutation
  state over writing the query cache. Basis for §4.
  [tkdodo: Concurrent Optimistic Updates][tk] ·
  [TanStack Query: Optimistic Updates][tanstack]
- **Stripe idempotency keys** — client-generated `Idempotency-Key`
  header; server stores the result and returns it on retry; compares
  params to reject misuse; key must be client-side so a retry reuses it.
  Basis for §3(d). [Stripe: Designing robust APIs with idempotency][stripe] ·
  [Stripe API: Idempotent requests][stripe-api]
- **SSE `Last-Event-ID` resume** — client sends `Last-Event-ID` on
  reconnect; server replays missed events from that cursor then tails
  live. Already partially implemented here
  (`GET /runs/{run_id}/events`, `id:` stamping in `chat.py:940-955`,
  `lastEventIdRef` in `use-send-message.ts:149`). [MDN: Using SSE][mdn]

[aisdk]: https://ai-sdk.dev/docs/ai-sdk-ui/chatbot-resume-streams
[aisdk-msg]: https://ai-sdk.dev/docs/ai-sdk-ui/chatbot-resume-streams
[au]: https://www.assistant-ui.com/docs/api-reference/runtimes/thread-runtime
[cc]: https://github.com/anthropics/claude-code/issues/50246
[tk]: https://tkdodo.eu/blog/concurrent-optimistic-updates-in-react-query
[tanstack]: https://tanstack.com/query/v5/docs/framework/react/guides/optimistic-updates
[stripe]: https://stripe.com/blog/idempotency
[stripe-api]: https://docs.stripe.com/api/idempotent_requests
[mdn]: https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
