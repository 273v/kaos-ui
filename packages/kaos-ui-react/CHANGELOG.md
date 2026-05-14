# Changelog — @273v/kaos-ui-react

All notable changes to this package are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Package skeleton: pnpm workspace, tsup build (ESM + CJS + d.ts),
  subpath exports (`/chat`, `/debug`, `/hooks`, `/lib`,
  `/styles.css`, `/tailwind.preset`).
- Theme tokens — CSS variables for the surface palette + the JSON tree
  + the markdown base styles. Mirrors the kaos-agents run inspector
  palette and is shadcn-naming-compatible.
- Tailwind 4 preset mapping the CSS variables to theme colors.
