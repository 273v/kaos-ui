/**
 * Best-effort clipboard write that works around the most common
 * `navigator.clipboard` failure modes:
 *
 *   - **Document not focused.** Some browsers (and headless Chrome
 *     in particular) reject ``writeText`` with a
 *     ``NotAllowedError`` when the page isn't focused, even if the
 *     write originated from a user gesture. We catch and fall back.
 *   - **Insecure context.** ``navigator.clipboard`` is ``undefined``
 *     on plain ``http://`` (non-localhost). The fallback path uses
 *     a hidden textarea + ``document.execCommand("copy")``, which
 *     is deprecated but still works everywhere shipping today.
 *   - **Permissions Policy block.** Iframes / sandboxed frames can
 *     have ``clipboard-write`` removed; the fallback bypasses the
 *     async API entirely.
 *
 * Returns ``true`` on success so the caller can update its visual
 * state ("copied / failed"). Never throws — failure surfaces as a
 * ``false`` return.
 */

export async function copyToClipboard(text: string): Promise<boolean> {
  // Modern path — fast, async, no DOM scribbling.
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall through to legacy path.
  }

  // Legacy fallback: hidden textarea + execCommand. The textarea
  // must be in the live DOM tree and visible-ish to select() in
  // some browsers, so we position it off-screen rather than
  // ``display: none``.
  if (typeof document === "undefined") return false;
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.left = "-9999px";
  ta.style.top = "0";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  try {
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, ta.value.length);
    const ok = document.execCommand("copy");
    return ok;
  } catch {
    return false;
  } finally {
    document.body.removeChild(ta);
  }
}
