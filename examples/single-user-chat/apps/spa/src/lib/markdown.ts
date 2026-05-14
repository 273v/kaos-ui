// markdown-it instance with a strict link sanitizer + safe defaults.
//
// LOW #3 — pre-fix, assistant content was rendered as `whitespace-pre-wrap`
// plain text, which meant **bold**, lists, code blocks, etc. shipped as
// raw asterisks. The agent's output is markdown by convention.
//
// Sanitization choices:
// - html: false → never trust raw <script> from the model
// - linkify: false → only render explicit [text](url), not bare URLs
//   (bare URLs are still readable as plain text)
// - validateLink override → http(s) and mailto only; everything else
//   (javascript:, data:, file:, ftp:, etc.) is dropped to a plain string

import MarkdownIt from "markdown-it";

const ALLOWED_LINK_SCHEMES = /^(https?|mailto):/i;

const md = new MarkdownIt({
  html: false,
  linkify: false,
  breaks: true,
  typographer: false,
});

const _validateLink = md.validateLink.bind(md);
md.validateLink = (url: string): boolean => {
  // Allow same-document anchors.
  if (url.startsWith("#")) return true;
  if (!ALLOWED_LINK_SCHEMES.test(url)) return false;
  return _validateLink(url);
};

// Open external links in a new tab + set rel="noopener noreferrer".
md.renderer.rules.link_open = (tokens, idx, options, _env, self) => {
  const token = tokens[idx];
  if (!token) return self.renderToken(tokens, idx, options);
  const href = token.attrGet("href") ?? "";
  if (href.startsWith("http")) {
    token.attrSet("target", "_blank");
    token.attrSet("rel", "noopener noreferrer");
  }
  return self.renderToken(tokens, idx, options);
};

export function renderMarkdown(source: string): string {
  return md.render(source);
}
