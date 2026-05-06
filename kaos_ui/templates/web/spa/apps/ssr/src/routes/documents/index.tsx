import { createFileRoute } from "@tanstack/react-router";
import { useDocuments } from "@kaos/ui/hooks/use-documents";

export const Route = createFileRoute("/documents/")({
  component: DocumentsPage,
});

function DocumentsPage() {
  const { data: documents, isLoading, error } = useDocuments();

  if (isLoading) return <p className="text-muted-foreground">Loading...</p>;
  if (error) return <p className="text-destructive">Error: {error.message}</p>;

  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-bold mb-4">Documents</h1>
      {documents?.length === 0 ? (
        <p className="text-muted-foreground">No documents found.</p>
      ) : (
        <ul className="space-y-2">
          {documents?.map((doc) => (
            <li
              key={doc.id}
              className="border border-border rounded-md p-4 flex justify-between items-center"
            >
              <div>
                <p className="font-medium">{doc.name}</p>
                <p className="text-sm text-muted-foreground">{doc.mime_type}</p>
              </div>
              <span className="text-sm text-muted-foreground">
                {(doc.size / 1024).toFixed(1)} KB
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
