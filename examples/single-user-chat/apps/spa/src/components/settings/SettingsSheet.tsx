// Right-side sheet per UX-LANGUAGE.md § 4.7. Single scrollable column.
// Triggered from the chat header (or by a future keyboard shortcut).

import { Button } from "@kaos-chat-example/ui/components/ui/button";
import { Textarea } from "@kaos-chat-example/ui/components/ui/textarea";
import { X } from "lucide-react";
import { useEffect, useState } from "react";

import { useModels } from "@/hooks/use-models";
import { usePatchMeta } from "@/hooks/use-patch-meta";
import type { SessionMeta } from "@/lib/api-types";

interface Props {
  open: boolean;
  onClose: () => void;
  meta: SessionMeta;
}

export function SettingsSheet({ open, onClose, meta }: Props) {
  const models = useModels();
  const patch = usePatchMeta(meta.id);

  // Local edit buffer — only commits to the server on Save.
  const [title, setTitle] = useState(meta.title);
  const [model, setModel] = useState(meta.model);
  const [systemPrompt, setSystemPrompt] = useState(meta.system_prompt);
  const [toolsEnabled, setToolsEnabled] = useState(meta.tools_enabled);

  useEffect(() => {
    if (open) {
      setTitle(meta.title);
      setModel(meta.model);
      setSystemPrompt(meta.system_prompt);
      setToolsEnabled(meta.tools_enabled);
    }
  }, [open, meta]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && open) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const onSave = async () => {
    await patch.mutateAsync({
      title,
      model,
      system_prompt: systemPrompt,
      tools_enabled: toolsEnabled,
    });
    onClose();
  };

  return (
    <>
      <div className="fixed inset-0 z-40 bg-foreground/10" onClick={onClose} aria-hidden />
      <aside
        className="fixed inset-y-0 right-0 z-50 w-full max-w-md bg-background border-l border-border shadow-none overflow-y-auto"
        role="dialog"
        aria-label="Session settings"
      >
        <header className="flex items-center justify-between px-5 py-4 border-b border-border sticky top-0 bg-background">
          <h2 className="text-base font-medium">Session settings</h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded hover:bg-muted text-muted-foreground"
            aria-label="Close settings"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="p-5 space-y-6">
          <Field label="Title">
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full h-9 px-3 rounded-md border border-input bg-background text-sm"
            />
          </Field>

          <Field label="Model" hint="Applies to the next turn.">
            <select
              value={model}
              disabled={models.isLoading}
              onChange={(e) => setModel(e.target.value)}
              className="w-full h-9 px-2 rounded-md border border-input bg-background text-sm"
            >
              {(models.data?.models ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </Field>

          <Field
            label="System prompt"
            hint="Instructions threaded as `instructions` on every turn."
          >
            <Textarea
              rows={6}
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              className="resize-y"
            />
          </Field>

          <Field label="Tools" hint="When on, the agent can call read-only KAOS document tools.">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={toolsEnabled}
                onChange={(e) => setToolsEnabled(e.target.checked)}
                className="h-4 w-4"
              />
              Enable read-only tools
            </label>
          </Field>

          {patch.isError && (
            <div className="text-sm text-destructive border border-destructive/30 rounded-md px-3 py-2">
              {patch.error instanceof Error ? patch.error.message : "Save failed."}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2 border-t border-border">
            <Button variant="ghost" onClick={onClose} disabled={patch.isPending}>
              Cancel
            </Button>
            <Button onClick={onSave} disabled={patch.isPending}>
              {patch.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
      </aside>
    </>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="text-xs font-medium">{label}</span>
        {hint && <span className="text-[11px] text-muted-foreground">{hint}</span>}
      </div>
      {children}
    </div>
  );
}
