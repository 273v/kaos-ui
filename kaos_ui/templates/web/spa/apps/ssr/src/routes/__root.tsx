import {
  createRootRoute,
  HeadContent,
  Link,
  Outlet,
  Scripts,
} from "@tanstack/react-router";
import { QueryClientProvider } from "@tanstack/react-query";
import { createQueryClient } from "@kaos/ui/lib/query-client";
import "@kaos/ui/styles/globals.css";

const queryClient = createQueryClient();

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1.0" },
      { title: "{{KAOS_PROJECT_NAME}}" },
    ],
  }),
  component: () => (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        <QueryClientProvider client={queryClient}>
          <div className="min-h-screen bg-background text-foreground">
            <nav className="border-b border-border px-6 py-3 flex gap-4">
              <Link to="/" className="font-semibold hover:text-primary">
                Home
              </Link>
              <Link to="/documents" className="hover:text-primary">
                Documents
              </Link>
              <Link to="/search" className="hover:text-primary">
                Search
              </Link>
            </nav>
            <main className="p-6">
              <Outlet />
            </main>
          </div>
        </QueryClientProvider>
        <Scripts />
      </body>
    </html>
  ),
});
