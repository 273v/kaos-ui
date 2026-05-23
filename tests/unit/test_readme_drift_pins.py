"""Regression test for audit-04: kaos_ui README count drift prevention.

audit-04/kaos-ui.md flagged that README.md:120 said
``kaos_ui.__all__`` had 18 symbols. Runtime inspection returned 19.
This test pins the exact count + the symbol set so future drift
fails the gate rather than silently making the README false.
"""

from __future__ import annotations

import kaos_ui

# The 19 names currently in kaos_ui.__all__ (audit-04 2026-05-23
# probe). Hardcoded as the source of truth so adding or removing
# any public name forces a README + CHANGELOG update.
_EXPECTED_PUBLIC_API: frozenset[str] = frozenset(
    {
        "KaosUIError",
        "KaosUISettings",
        "PostInstallError",
        "ScaffoldError",
        "ScaffoldResult",
        "TEMPLATES",
        "TargetExistsError",
        "TemplateManifest",
        "UnknownTemplateError",
        "__version__",
        "get_manifest",
        "kinds",
        "list_templates",
        "register_alias",
        "register_kaos_ui_tools",
        "register_template",
        "register_ui_tools",
        "resolve_kind",
        "scaffold",
    }
)


def test_dunder_all_count_matches_readme() -> None:
    """README.md:120 says 19 symbols. Pin the exact count.

    The count was 18 pre-2026-05-23; the README is now correct and
    this test keeps it in sync.
    """
    assert len(kaos_ui.__all__) == 19, (
        "audit-04 README drift regression: kaos_ui.__all__ count moved "
        f"from the documented 19 (now {len(kaos_ui.__all__)}). "
        "Update README.md:120 Maturity row + CHANGELOG before changing __all__."
    )


def test_dunder_all_matches_expected_set() -> None:
    """Pin the exact 19-symbol set, not just the count."""
    actual = frozenset(kaos_ui.__all__)
    assert actual == _EXPECTED_PUBLIC_API, (
        "audit-04 README drift regression: kaos_ui.__all__ set moved.\n"
        f"  added:   {sorted(actual - _EXPECTED_PUBLIC_API)}\n"
        f"  removed: {sorted(_EXPECTED_PUBLIC_API - actual)}\n"
        "Update README.md:120 + CHANGELOG before changing __all__."
    )
