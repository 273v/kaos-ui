// DropZone — full-viewport drag-and-drop overlay that catches files
// dropped anywhere on the page and forwards them to the parent's
// onDrop handler.
//
// We listen on `document` (not just a single ref) so the user can
// drop a file anywhere in the chat surface — top bar, sidebar,
// composer area — and have it land. The overlay only appears while
// a drag containing files is active (dragenter/dragleave bookkeep a
// nesting counter to avoid flicker when the cursor moves over
// child elements).
//
// Uploads are dispatched serially via `onDrop(file)` per file so the
// parent can surface per-file errors and progress.

import { Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";

interface Props {
  /** Called once per File on drop. Parent decides how to enqueue uploads. */
  onDrop: (file: File) => void;
  /** Stops new drops from being accepted (e.g., no active session). */
  disabled?: boolean;
  /** Optional accept list (extension globs). Defaults to PDF / DOCX / PPTX. */
  accept?: ReadonlySet<string>;
}

const DEFAULT_ACCEPT = new Set([".pdf", ".docx", ".pptx"]);

export function DropZone({ onDrop, disabled = false, accept = DEFAULT_ACCEPT }: Props) {
  const [active, setActive] = useState(false);
  // Drag events fire on every nested element under the cursor. A
  // depth counter lets us only deactivate when the user actually
  // leaves the document (depth → 0), not when they move between
  // children.
  const depth = useRef(0);

  useEffect(() => {
    if (disabled) {
      setActive(false);
      depth.current = 0;
      return;
    }
    const onDragEnter = (e: DragEvent) => {
      if (!e.dataTransfer?.types.includes("Files")) return;
      depth.current += 1;
      setActive(true);
    };
    const onDragOver = (e: DragEvent) => {
      // Must preventDefault to mark the page as a drop target.
      if (!e.dataTransfer?.types.includes("Files")) return;
      e.preventDefault();
    };
    const onDragLeave = (e: DragEvent) => {
      if (!e.dataTransfer?.types.includes("Files")) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setActive(false);
    };
    const onDropEvent = (e: DragEvent) => {
      if (!e.dataTransfer?.files || e.dataTransfer.files.length === 0) return;
      e.preventDefault();
      depth.current = 0;
      setActive(false);
      for (const file of Array.from(e.dataTransfer.files)) {
        const dot = file.name.lastIndexOf(".");
        const ext = dot === -1 ? "" : file.name.slice(dot).toLowerCase();
        if (!accept.has(ext)) {
          // Silent skip for unsupported extensions — backend would
          // 415 it anyway, but rejecting here avoids a wasted round
          // trip + surfaces nothing surprising in DevTools.
          continue;
        }
        onDrop(file);
      }
    };

    document.addEventListener("dragenter", onDragEnter);
    document.addEventListener("dragover", onDragOver);
    document.addEventListener("dragleave", onDragLeave);
    document.addEventListener("drop", onDropEvent);
    return () => {
      document.removeEventListener("dragenter", onDragEnter);
      document.removeEventListener("dragover", onDragOver);
      document.removeEventListener("dragleave", onDragLeave);
      document.removeEventListener("drop", onDropEvent);
    };
  }, [disabled, onDrop, accept]);

  if (!active) return null;

  return (
    <div
      aria-hidden
      className={
        "fixed inset-0 z-50 flex items-center justify-center bg-background/80 " +
        "backdrop-blur-sm pointer-events-none"
      }
    >
      <div className="rounded-lg border-2 border-dashed border-primary/60 bg-card px-8 py-10 shadow-lg">
        <div className="flex flex-col items-center gap-3">
          <Upload className="h-10 w-10 text-primary" aria-hidden />
          <p className="text-lg font-medium">Drop files to upload</p>
          <p className="text-sm text-muted-foreground">PDF, DOCX, or PPTX</p>
        </div>
      </div>
    </div>
  );
}
