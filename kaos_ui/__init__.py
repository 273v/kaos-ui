"""kaos-ui — project scaffolding for KAOS user-facing applications."""

from kaos_ui._version import __version__
from kaos_ui.exceptions import (
    KaosUIError,
    PostInstallError,
    ScaffoldError,
    TargetExistsError,
    UnknownTemplateError,
)
from kaos_ui.manifest import (
    TEMPLATES,
    TemplateManifest,
    get_manifest,
    kinds,
    list_templates,
    register_alias,
    register_template,
    resolve_kind,
)
from kaos_ui.runtime import register_kaos_ui_tools
from kaos_ui.scaffolder import scaffold
from kaos_ui.settings import KaosUISettings

__all__ = [
    "TEMPLATES",
    "KaosUIError",
    "KaosUISettings",
    "PostInstallError",
    "ScaffoldError",
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
    "resolve_kind",
    "scaffold",
]
