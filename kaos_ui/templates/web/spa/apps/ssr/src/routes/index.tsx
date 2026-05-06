import { createFileRoute, Link } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  component: HomePage,
});

function HomePage() {
  return (
    <div className="max-w-2xl">
      <h1 className="text-3xl font-bold mb-4">{{KAOS_PROJECT_NAME}}</h1>
      <p className="text-muted-foreground mb-6">
        Full-stack application powered by KAOS, FastAPI, and React.
      </p>
      <Link
        to="/documents"
        className="inline-block px-4 py-2 bg-primary text-primary-foreground rounded-md hover:opacity-90"
      >
        Browse Documents
      </Link>
    </div>
  );
}
