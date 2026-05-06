/**
 * Self-hosted font side-effect imports. Importing this module from
 * the SPA entry (`main.tsx`) loads Inter Variable + Source Serif 4
 * Variable via @fontsource — no Google Fonts CDN call.
 *
 * Variable fonts give the full weight + optical-size range in a
 * single file each, which is why we don't import per-weight subsets.
 */
import "@fontsource-variable/inter";
import "@fontsource-variable/source-serif-4";
