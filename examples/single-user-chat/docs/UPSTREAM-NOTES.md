# Upstream notes — kaos-agents footguns that bit this example

> Status: draft. Updated 2026-05-14 based on `kaos-agents==0.1.0a1`,
> `kaos-core==0.1.0a6`, `kaos-mcp` (workspace copy), `kaos-llm-client==0.1.0a3`.
>
> These notes document three real footguns in kaos-agents' bundled
> FastAPI surface that we worked around inside this example. **They
> are inconsistencies with the rest of the kaos ecosystem** — sibling
> packages (kaos-core, kaos-mcp) already do the right thing. The
> example codifies the workarounds; this doc captures *why* and what
> upstream should change so the workarounds can be deleted.

## How we verified the contradiction

`grep`-walked all kaos-* packages and found:

- **kaos-core** (`kaos_core/registry/container.py:32-55`): docstring on
  `KaosRuntime` says "the default VFS backend is `StorageBackend.DISK`
  rooted at `.kaos-vfs/`". The class constructor honors this:
  `self._vfs = vfs if vfs is not None else VirtualFileSystem()` —
  and `VirtualFileSystem()`'s default `VFSConfig` is `DISK`-backed.
  The ecosystem default is disk.
- **kaos-mcp** (`kaos_mcp/adapters/resource.py:83`): when a tool runs
  through kaos-mcp's resource adapter, the adapter explicitly
  constructs `context = KaosContext.create(runtime=self._runtime)`.
  This is the exact pattern we monkey-patched into kaos-agents.
- **kaos-agents** itself (`kaos_agents/cli/chat.py:995`,
  `kaos_agents/retrieval_agent.py:91`): registers tools onto a runtime
  before constructing the Agent — so the package knows this is the
  canonical setup pattern. The `create_app()` HTTP path is the only
  place that skips it.

The HTTP API path is therefore the outlier. Three concrete defects
follow.

---

## P-020 — `create_app(runtime=None)` defaults to in-memory VFS, contradicting kaos-core

**Symptom.** Conversations evaporate on backend restart. SessionMemory
data exists in-process while the agent is replying, but the moment
uvicorn restarts the kaos-agents-side history is gone.

**Source.** `kaos_agents/api/server.py` `_resolve_vfs`:

```python
def _resolve_vfs(runtime: KaosRuntime | None) -> VirtualFileSystem:
    if runtime is not None and hasattr(runtime, "vfs") and runtime.vfs is not None:
        return runtime.vfs
    config = VFSConfig(default_backend=StorageBackend.MEMORY)   # ← !
    return VirtualFileSystem(config=config)
```

**Why this is wrong.** kaos-core's `KaosRuntime()` default is DISK
(see `kaos_core/registry/container.py:32` docstring + `VFSConfig`
default at `kaos_core/vfs/models.py`). The `_resolve_vfs` fallback
silently switches the storage backend to MEMORY, breaking the
sensible ecosystem default and producing silent data loss.

**Suggested upstream fix.**

```python
def _resolve_vfs(runtime: KaosRuntime | None) -> VirtualFileSystem:
    if runtime is not None and hasattr(runtime, "vfs") and runtime.vfs is not None:
        return runtime.vfs
    # Match kaos-core's default — disk. If the caller wants memory,
    # they pass a `KaosRuntime` with a memory-backed VFS explicitly.
    return VirtualFileSystem()
```

Or refuse to start without an explicit runtime (mirroring the
auth-required gate already in `create_app`).

**Workaround in this example.** `backend/app/main.py` constructs a
disk-backed `KaosRuntime` and passes it to `create_app(runtime=...)`.

---

## P-021 — `Runner` only attaches a `KaosContext` when `corpus is not None`, leaving bridged tools with no runtime

**Symptom.** Every tool call fails with
`{"error": true, "message": "No runtime context..."}` even though
the runtime was constructed correctly and tools were registered.

**Source.** `kaos_agents/runtime/runner.py:151-158`:

```python
if context is None and corpus is not None:
    from kaos_core.base.context import KaosContext
    context = KaosContext.create()
if context is not None and corpus is not None:
    context._config["_corpus"] = corpus
self._context = context
```

Then `bridge_runtime_tools(self._runtime, self._context, ...)` (line
278) passes `None` for context — and the bridged tool wrapper hands
that `None` to `KaosTool.execute(inputs, context=None)`, which fails
the runtime-availability check inside every kaos-core tool.

**Why this is wrong.** kaos-mcp (`kaos_mcp/adapters/resource.py:83`)
already does the right thing for the MCP path:

```python
context = KaosContext.create(runtime=self._runtime)
```

So the ecosystem precedent is "always thread a runtime-attached
context when there are tools." kaos-agents' Runner skips this step
in the no-corpus case, leaving HTTP-served chat agents toolless.

**Suggested upstream fix** (Runner.__init__):

```python
# Always provide a context if we have a runtime to attach. The
# context's `_corpus` plumbing already short-circuits when corpus
# is None, so this change is purely about tool execution.
if context is None and runtime is not None:
    from kaos_core.base.context import KaosContext
    context = KaosContext.create(runtime=runtime)
if context is not None and corpus is not None:
    context._config["_corpus"] = corpus
self._context = context
```

**Workaround in this example.** `_install_tool_bridge_runtime_patch()`
in `backend/app/main.py` wraps `kaos_agents.actions.tool_bridge.bridge_runtime_tools`
to auto-create the context if the Runner didn't.

---

## P-022 — The agent is never told what tools it has

**Symptom.** Even with tools registered on the runtime and the
context fixed, asking the agent "what tools do you have access to?"
returns "No, I don't have any tools available." The LLM is never
informed of the toolset; ReAct only surfaces tools when the model
*decides* to call one — and the model can't decide to call a tool
it doesn't know exists.

**Why this is wrong.** Every other agent framework (OpenAI Assistants,
Anthropic native tools, kaos-llm-core's ReAct programs when called
directly) auto-includes the tool catalog in the system prompt. The
bundled kaos-agents HTTP API doesn't, so the LLM only "discovers"
tools mid-trial-and-error.

**Suggested upstream fix.** In `kaos_agents/patterns/chat.py` (or
wherever the ReAct prompt is assembled), when `bridged_tools` is
non-empty, prepend the canonical-name list to `instructions`:

```
"You have access to the following tools:\n"
+ "\n".join(f"- {t.name}: {t.description}" for t in bridged_tools)
+ "\n\nCall them when relevant.\n\n"
+ user_instructions
```

**Workaround in this example.** `app/services/stream_proxy.py`'s
`_instructions_with_tool_state()` reads the available tool name list
from the runtime and prepends it to `MessageRequest.instructions`.

---

## P-023 — `KAOS_AGENTS_API_*` env var prefix is doubled (this one's just confusing, not broken)

`kaos_agents/api/settings.py` declares `env_prefix="KAOS_AGENTS_API_"`
on a `KaosAgentsApiSettings` whose field names start with `api_`. So
`api_token` becomes the env var `KAOS_AGENTS_API_API_TOKEN`
(pydantic-settings concatenates prefix + field name verbatim).

The package's own error message in `_resolve_vfs` reports the wrong
form (`KAOS_AGENTS_API_TOKEN`), making this hard to diagnose
without reading the source.

**Suggested upstream fix.** Either (a) drop the `api_` prefix from
the field names so the env vars become `KAOS_AGENTS_API_TOKEN`,
`KAOS_AGENTS_API_CORS_ALLOW_ORIGINS`, etc., or (b) fix the error
message to print the actual var names.

---

## Versioning + when to remove the workarounds

The four patches above all live in `backend/app/main.py` +
`backend/app/services/stream_proxy.py`. When kaos-agents publishes
a release that fixes any of them:

1. Bump the kaos-agents pin in `backend/pyproject.toml`.
2. Run the example's QA gate (`make doctor`).
3. Remove the corresponding workaround.
4. Add a `pytest.skip` or `pytest.skipIf` on the workaround-specific
   tests so they don't fail loud on the new behavior.

Track upstream resolution against this doc — when all four are
fixed, this whole file can move to `docs/HISTORICAL-NOTES.md` and
the example becomes ~80 lines shorter.

## Why we chose to fix in the example rather than upstream

We don't (yet) have commit access to the `273v/kaos-agents` per-module
repo. This doc is the deliverable until that changes. Once we can PR
upstream, the patches above are tiny — each is 5-15 lines.
