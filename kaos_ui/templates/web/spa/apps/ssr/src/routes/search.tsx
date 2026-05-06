import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { searchDocuments } from "@kaos/ui/lib/api";

export const Route = createFileRoute("/search")({
  component: SearchPage,
});

function SearchPage() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");

  const { data: results, isLoading } = useQuery({
    queryKey: ["search", submitted],
    queryFn: () => searchDocuments(submitted),
    enabled: submitted.length > 0,
  });

  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-bold mb-4">Search</h1>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(query);
        }}
        className="flex gap-2 mb-6"
      >
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search documents..."
          className="flex-1 border border-input rounded-md px-3 py-2 bg-background"
        />
        <button
          type="submit"
          className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:opacity-90"
        >
          Search
        </button>
      </form>

      {isLoading && <p className="text-muted-foreground">Searching...</p>}

      {results && (
        <ul className="space-y-3">
          {results.length === 0 ? (
            <p className="text-muted-foreground">No results found.</p>
          ) : (
            results.map((r, i) => (
              <li key={i} className="border border-border rounded-md p-4">
                <div className="flex justify-between items-start mb-1">
                  <p className="font-medium">{r.document.name}</p>
                  <span className="text-sm text-muted-foreground">
                    {r.score.toFixed(2)}
                  </span>
                </div>
                <p className="text-sm text-muted-foreground">{r.snippet}</p>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
