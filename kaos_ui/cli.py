"""``kaos-ui`` CLI.

Follows ``docs/guides/cli-standard.md``: ``main(argv)`` signature, every
structured command supports ``--json`` with the ``command``+payload
envelope, errors go to stderr, lazy imports keep ``--help`` fast.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _json_out(data: dict[str, Any]) -> None:
    print(json.dumps(data, indent=2, default=str))


def _error(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def _cmd_list(args: argparse.Namespace) -> None:
    from kaos_ui.manifest import list_templates

    manifests = list_templates()
    if args.json:
        _json_out(
            {
                "command": "list",
                "templates": [
                    {
                        "kind": m.kind,
                        "description": m.description,
                        "stack": m.stack,
                        "tags": list(m.tags),
                    }
                    for m in manifests
                ],
            }
        )
        return
    print("Available templates:")
    for m in manifests:
        print(f"  {m.kind:<24} {m.description}")


def _cmd_info(args: argparse.Namespace) -> None:
    from kaos_ui.exceptions import UnknownTemplateError
    from kaos_ui.manifest import get_manifest

    try:
        manifest = get_manifest(args.kind)
    except UnknownTemplateError as exc:
        _error(str(exc))
        return

    payload = {
        "command": "info",
        "kind": manifest.kind,
        "description": manifest.description,
        "stack": manifest.stack,
        "template_dir": str(manifest.template_dir),
        "required_env": list(manifest.required_env),
        "post_install": list(manifest.post_install),
        "next_steps": list(manifest.next_steps),
        "tags": list(manifest.tags),
    }

    if args.json:
        _json_out(payload)
        return
    print(f"{manifest.kind} — {manifest.description}")
    print(f"  stack:        {manifest.stack}")
    print(f"  template:     {manifest.template_dir}")
    if manifest.required_env:
        print(f"  required env: {', '.join(manifest.required_env)}")
    if manifest.post_install:
        print(f"  post-install: {' && '.join(manifest.post_install)}")
    if manifest.next_steps:
        print("  next steps:")
        for step in manifest.next_steps:
            print(f"    {step}")


def _cmd_new(args: argparse.Namespace) -> None:
    from kaos_ui.exceptions import KaosUIError
    from kaos_ui.scaffolder import scaffold

    target = Path(args.target).resolve() if args.target else None

    try:
        result = scaffold(
            args.kind,
            args.name,
            target_dir=target,
            ssr=args.ssr,
            dry_run=args.dry_run,
        )
    except KaosUIError as exc:
        _error(str(exc))
        return

    if args.json:
        _json_out({"command": "new", **result})
        return

    if result.get("dry_run"):
        print(
            f"Would create {args.name}/ from {result['template']!r} ({len(result['files'])} files)"
        )
        for f in result["files"]:
            print(f"  {f}")
        return

    print(f"Created {result['target']} from {result['template']!r} ({len(result['files'])} files)")

    # Next-steps hint from the manifest.
    from kaos_ui.manifest import get_manifest

    manifest = get_manifest(result["template"])
    if manifest.next_steps:
        print()
        for step in manifest.next_steps:
            print(f"  {step.format(name=args.name)}")


def _cmd_doctor(args: argparse.Namespace) -> None:
    from kaos_ui.doctor import run_doctor

    target = Path(args.path).resolve() if args.path else Path.cwd()
    report = run_doctor(target)

    if args.json:
        _json_out({"command": "doctor", **report.to_dict()})
        return

    status = "ok" if report.ok else "issues found"
    print(f"doctor: {status} ({report.path})")
    for finding in report.findings:
        print(f"  [{finding.severity}] {finding.what}")
        print(f"      → {finding.how_to_fix}")
        if finding.alternative_tool:
            print(f"      alt: {finding.alternative_tool}")
    if not report.ok:
        sys.exit(1)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kaos-ui",
        description="Scaffold, configure, and validate KAOS user-facing applications",
    )
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="List available template kinds")
    p_list.add_argument("--json", action="store_true", help="JSON output")

    p_info = sub.add_parser("info", help="Show details for one kind")
    p_info.add_argument("kind", help="Template kind, e.g. web:spa")
    p_info.add_argument("--json", action="store_true", help="JSON output")

    p_new = sub.add_parser("new", help="Scaffold a new project from a kind")
    p_new.add_argument("kind", help="Template kind, e.g. web:spa, dashboard:streamlit")
    p_new.add_argument("name", help="Project name (becomes the directory)")
    p_new.add_argument("--target", help="Target directory (default: ./<name>)")
    p_new.add_argument("--ssr", action="store_true", help="Use SSR variant (web:spa only)")
    p_new.add_argument("--dry-run", action="store_true", help="Show what would be created")
    p_new.add_argument("--json", action="store_true", help="JSON output")

    p_doctor = sub.add_parser("doctor", help="Health-check a scaffolded project")
    p_doctor.add_argument("path", nargs="?", help="Project root (default: cwd)")
    p_doctor.add_argument("--json", action="store_true", help="JSON output")

    return parser


def main(argv: list[str] | None = None) -> None:
    """Entry point. ``argv`` parameter exists for testability."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    handlers = {
        "list": _cmd_list,
        "info": _cmd_info,
        "new": _cmd_new,
        "doctor": _cmd_doctor,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
