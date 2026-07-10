export type PermissionLevel = "read" | "write" | "execute" | "external_publish" | "dangerous";

export interface AgentDefinition {
  id: string;
  name: string;
  display_name: string;
  description: string;
  enabled: boolean;
  default_model: string;
  workspace_dir: string;
  allowed_paths: string[];
  permission_level: PermissionLevel;
  equipped_skills: string[];
  status: string;
}

export interface SkillDefinition {
  id: string;
  name: string;
  display_name: string;
  description: string;
  category: string;
  version: string;
  enabled: boolean;
  triggers: string[];
  owner_agents: string[];
  permission_level: PermissionLevel;
  confirm_required: boolean;
}

export interface ToolDefinition {
  id: string;
  name: string;
  display_name: string;
  description: string;
  owner_skill: string;
  permission_level: PermissionLevel;
  timeout_seconds: number;
  enabled: boolean;
}

export interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  agent_name?: string;
  trace_id?: string;
  created_at: string;
}

export interface ChatEvent {
  event: string;
  trace_id: string;
  message: string;
  agent?: string;
  skill?: string;
  data: Record<string, unknown>;
}

export interface MetricOverview {
  total_calls: number;
  success_rate: number;
  failed_calls: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  token_usage: number;
  cost_estimate: number;
  recent_errors: unknown[];
}

