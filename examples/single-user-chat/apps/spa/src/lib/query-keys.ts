// Centralized TanStack Query keys.

export const queryKeys = {
  sessions: () => ["chat", "sessions"] as const,
  session: (id: string) => ["chat", "session", id] as const,
  models: () => ["models"] as const,
};
