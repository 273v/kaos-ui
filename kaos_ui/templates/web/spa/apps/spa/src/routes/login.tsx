import { Button } from "@{{KAOS_NPM_SLUG}}/ui/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@{{KAOS_NPM_SLUG}}/ui/components/ui/card";
import { Input } from "@{{KAOS_NPM_SLUG}}/ui/components/ui/input";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";

import { useAuth } from "@/auth/context";

export const Route = createFileRoute("/login")({
  validateSearch: (search) => ({
    redirect: typeof search.redirect === "string" ? search.redirect : undefined,
  }),
  component: LoginPage,
});

function LoginPage() {
  const auth = useAuth();
  const { redirect } = Route.useSearch();
  const navigate = useNavigate();
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await auth.login(token);
      navigate({ to: redirect ?? "/chat" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="font-display text-2xl font-normal">Welcome back</CardTitle>
          <CardDescription>Enter your access token to continue.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="login-token" className="text-xs font-medium text-muted-foreground">
                Access token
              </label>
              <Input
                id="login-token"
                type="password"
                autoComplete="current-password"
                required
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="•••••••••••••••••"
              />
              <p className="text-xs text-muted-foreground">
                Set <code className="font-mono">APP_AUTH_TOKEN</code> in{" "}
                <code className="font-mono">.env</code>.
              </p>
            </div>
            {error ? (
              <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </p>
            ) : null}
            <Button type="submit" disabled={submitting} className="w-full">
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
