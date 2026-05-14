// Login route. Single textarea-style field for the kaos-agents bearer.
//
// On success we navigate to `?redirect=` (carrying the original
// destination if the user was bounced here from `_auth`) or `/sessions`.

import { Button } from "@kaos-chat-example/ui/components/ui/button";
import { Input } from "@kaos-chat-example/ui/components/ui/input";
import { useMutation } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { z } from "zod";

import { useAuth } from "@/auth/context";

const SearchSchema = z.object({
  redirect: z.string().optional(),
});

export const Route = createFileRoute("/login")({
  validateSearch: (search) => SearchSchema.parse(search),
  component: LoginRoute,
});

/**
 * Allowlist a `redirect` search param to known same-app paths.
 *
 * Rejects:
 *   - any non-string / empty value → fall back to `/sessions`
 *   - protocol-relative URLs (`//evil.com`) — these would navigate
 *     off-origin via the browser's URL parser
 *   - absolute URLs (`http://`, `mailto:`, `javascript:`, etc.)
 *   - anything that doesn't start with a single `/`
 *
 * This is defense-in-depth — TanStack Router will already refuse to
 * navigate to anything that doesn't match a registered route, but a
 * future refactor that uses `window.location.assign(redirect)` would
 * regress without this guard.
 */
export function safeRedirect(raw: string | undefined): string {
  if (typeof raw !== "string" || raw.length === 0) return "/sessions";
  if (!raw.startsWith("/")) return "/sessions";
  if (raw.startsWith("//")) return "/sessions"; // protocol-relative
  if (raw.startsWith("/\\")) return "/sessions"; // path-traversal trick
  // Reject any character outside printable ASCII to dodge unicode
  // visual-confusion tricks (zero-width space, RTL override, etc.).
  // Same-app paths only need ASCII; consumers wanting real Unicode
  // in URLs should percent-encode (which is ASCII-safe).
  // biome-ignore lint/suspicious/noControlCharactersInRegex: deliberately filters control chars.
  if (!/^[\x20-\x7e]+$/.test(raw)) return "/sessions";
  return raw;
}

function LoginRoute() {
  const { redirect } = Route.useSearch();
  const navigate = useNavigate();
  const auth = useAuth();
  const [token, setToken] = useState("");

  const mutation = useMutation({
    mutationFn: (t: string) => auth.login(t),
    onSuccess: () => {
      navigate({
        to: safeRedirect(redirect),
        replace: true,
      });
    },
  });

  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center font-sans">
      <div className="w-full max-w-md px-8">
        <h1 className="text-4xl font-serif font-light mb-2">Single-User Chat</h1>
        <p className="text-sm text-muted-foreground mb-8">
          Sign in with your <code className="text-foreground">KAOS_AGENTS_API_API_TOKEN</code>.
        </p>

        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate(token);
          }}
        >
          <div>
            <label htmlFor="token" className="block text-xs font-medium mb-2">
              Bearer token
            </label>
            <Input
              id="token"
              type="password"
              autoComplete="current-password"
              autoFocus
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="32+ characters"
              disabled={mutation.isPending}
            />
          </div>

          {mutation.isError && (
            <div className="text-sm text-destructive border border-destructive/30 rounded-md px-3 py-2">
              {mutation.error instanceof Error
                ? mutation.error.message
                : "Sign-in failed. Check the token."}
            </div>
          )}

          <Button type="submit" className="w-full" disabled={mutation.isPending || !token}>
            {mutation.isPending ? "Verifying…" : "Sign in"}
          </Button>
        </form>

        <p className="mt-8 text-xs text-muted-foreground">
          Generate one with{" "}
          <code className="text-foreground">head -c 32 /dev/urandom | base64</code> and set it as{" "}
          <code className="text-foreground">KAOS_AGENTS_API_API_TOKEN</code> in your{" "}
          <Link to="/login" className="underline">
            .env
          </Link>
          .
        </p>
      </div>
    </div>
  );
}
