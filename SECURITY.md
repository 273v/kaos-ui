# Security policy

`kaos-ui` is the project scaffolder for KAOS user-facing applications.
The scaffolder reads bundled templates, materializes them onto disk,
and (optionally) runs vetted post-install commands. The threat surface
is small but real: an attacker who can substitute a template payload
or post-install command can compromise the resulting project.

## Reporting a vulnerability

If you believe you've found a vulnerability in this package, please
report it through one of the following channels, ordered by preference:

1. **GitHub private vulnerability reporting** — open a report at
   <https://github.com/273v/kaos-ui/security/advisories/new>. This
   routes directly to the maintainers with non-public scratch space
   for back-and-forth.
2. **Email** — <security@273ventures.com>. Encrypt with the
   organization PGP key published at <https://273ventures.com/pgp> if
   the report contains sensitive details.

Please **do not** open a public GitHub issue or pull request for a
suspected vulnerability before the fix has shipped.

## Disclosure window

We target a **90-day** coordinated-disclosure window from the date a
report is acknowledged. If the issue is publicly exploited in the wild
before the 90 days elapse, we may publish a fix and an advisory
earlier.

This window aligns with the disclosure policy across the rest of the
KAOS ecosystem (kaos-core, kaos-graph, kaos-source, etc.) and with the
Cyber Resilience Act's Annex I Part II §5 expectation for
coordinated-disclosure programs.

## Supported versions

Only the latest published `0.1.x` line receives security fixes during
the alpha phase. Once `0.1.0` ships out of alpha, support windows for
the prior minor line will be announced in the [CHANGELOG](CHANGELOG.md).

## Scope

### In scope

- The `kaos_ui` Python package (CLI + MCP tools + scaffolder + post-install runner).
- The bundled templates under `kaos_ui/templates/` — a template that
  embeds a backdoor in scaffolded projects is a security bug, not a
  template quality issue.
- The `kaos-ui-doctor` health-check logic — false negatives that hide
  real toolchain pwnage are in scope.

### Out of scope

- Vulnerabilities in third-party dependencies (`pydantic`, `kaos-core`,
  etc.) that are tracked upstream. Out-of-band reports are welcome but
  not required.
- "The scaffolded project's dependencies have a CVE" — that's the
  responsibility of the scaffolded project's maintainer. The template
  pins major versions only; consumers run their own pip-audit.

## Hall of fame

Reports that materially improve the security posture of `kaos-ui` will
be credited in the relevant changelog entry, with attribution at the
reporter's preference (name, handle, organization, or pseudonymous).
