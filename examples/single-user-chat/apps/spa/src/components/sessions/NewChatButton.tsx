import { Button } from "@kaos-chat-example/ui/components/ui/button";
import { useNavigate } from "@tanstack/react-router";
import { Plus } from "lucide-react";

import { useCreateSession } from "@/hooks/use-create-session";

export function NewChatButton() {
  const navigate = useNavigate();
  const mutation = useCreateSession();

  const onClick = async () => {
    const meta = await mutation.mutateAsync({});
    navigate({ to: "/sessions/$id", params: { id: meta.id } });
  };

  return (
    <Button
      type="button"
      variant="default"
      onClick={onClick}
      disabled={mutation.isPending}
      className="w-full justify-start gap-2"
    >
      <Plus className="h-4 w-4" />
      <span>{mutation.isPending ? "Creating…" : "New chat"}</span>
    </Button>
  );
}
