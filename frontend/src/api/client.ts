import type {
  AgentDefinition,
  ChatEvent,
  ChatMessage,
  ChatSession,
  MetricOverview,
  SkillDefinition,
  ToolDefinition
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // Shared JSON helper keeps page components focused on product behavior, not fetch details.
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; app: string; env: string }>("/health"),
  agents: () => request<AgentDefinition[]>("/agents"),
  updateAgent: (name: string, enabled: boolean) =>
    request<AgentDefinition>(`/agents/${name}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled })
    }),
  skills: () => request<SkillDefinition[]>("/skills"),
  tools: () => request<ToolDefinition[]>("/tools"),
  metrics: () => request<MetricOverview>("/statistics/overview"),
  mcps: () => request<Record<string, unknown>[]>("/mcps"),
  workflows: () => request<Record<string, unknown>[]>("/workflows"),
  documents: () => request<Record<string, unknown>[]>("/knowledge/documents"),
  settings: () => request<Record<string, unknown>>("/settings"),
  createSession: (workspaceDir?: string) =>
    request<ChatSession>("/chat/sessions", {
      method: "POST",
      body: JSON.stringify({ workspace_dir: workspaceDir ?? "" })
    }),
  sessions: () => request<ChatSession[]>("/chat/sessions"),
  session: (id: string) =>
    request<{ session: ChatSession; messages: ChatMessage[] }>(`/chat/sessions/${id}`),
  deleteSession: (id: string) =>
    request<void>(`/chat/sessions/${id}`, {
      method: "DELETE"
    })
};

export async function streamMessage(
  sessionId: string,
  content: string,
  agentName: string,
  workspaceDir: string,
  onEvent: (event: ChatEvent) => void
): Promise<void> {
  // Fetch streaming works with POST, unlike EventSource, and carries the selected Agent.
  const response = await fetch(`${API_BASE}/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, agent_name: agentName, workspace_dir: workspaceDir, entrypoint: "web_ui" })
  });
  if (!response.ok || !response.body) {
    throw new Error(await response.text());
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const packets = buffer.split("\n\n");
    buffer = packets.pop() ?? "";
    // Each SSE packet contains a JSON payload on its data line.
    for (const packet of packets) {
      const dataLine = packet.split("\n").find((line) => line.startsWith("data: "));
      if (!dataLine) continue;
      onEvent(JSON.parse(dataLine.slice(6)) as ChatEvent);
    }
  }
}
