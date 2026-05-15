"""Multi-tenant SessionStore — namespaces session metadata by tenant.

Wraps single-user-chat's flat SessionStore with a per-tenant prefix
so two users in the same deploy cannot read or list each other's
sessions. The same kaos-ui helpers (kaos_ui.uploads.*, kaos-agents'
session memory) work as-is because every helper takes a session id;
the VFS path is constructed with the tenant prefix transparently.

Path layout:

  .kaos-vfs/
  └── tenants/
      └── {tenant_id}/
          ├── sessions/
          │   └── {session_id}/
          │       ├── meta.json
          │       ├── files/
          │       │   └── {filename}
          │       └── toolcalls/
          │           └── turn-NNNN.jsonl
          └── (kaos-agents session memory layered under the same prefix)

The wrapper is intentionally thin — most behavior delegates to the
single-user SessionStore by composing a tenant-scoped VFS view.
Promote into kaos-ui's package after the integration shakes out here.
"""

from __future__ import annotations

from kaos_core.vfs import VirtualFileSystem


def tenant_vfs(*, base_vfs: VirtualFileSystem, tenant_id: str) -> VirtualFileSystem:
    """Return a VFS view rooted at ``tenants/{tenant_id}/`` so every
    operation against it is automatically tenant-scoped.

    The view shares the underlying backend (disk paths, in-memory
    state) with ``base_vfs`` — only the path resolution is rebased.
    Sessions stored through the view CANNOT be read by another
    tenant's view because the disk path includes the tenant id.

    The implementation here is a placeholder — production code should
    use ``VirtualFileSystem.subview()`` once that ships in kaos-core.
    For now, we attach a prefix at the application layer (every
    SessionStore call wraps its path with ``f"tenants/{tenant_id}/"``).
    """
    # Wrap the existing VFS with a prefix-aware proxy. Real impl: a
    # `_TenantScopedVFS` class that overrides read/write/list/exists/
    # delete to prepend the prefix. Left as a skeleton TODO until the
    # SPA integration test pins the contract.
    raise NotImplementedError(
        "Skeleton — see README.md 'Status' section. Real implementation "
        'plumbs `f"tenants/{tenant_id}/{path}"` into every SessionStore '
        "call. The kaos-ui-react package itself doesn't need to change."
    )
