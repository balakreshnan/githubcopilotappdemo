export type AgentRole = "main" | "connected";
export type StepStatus = "running" | "completed" | "failed";

export interface AgentInfo {
  id: string;
  name: string;
  description: string;
  role: AgentRole;
}

export interface Source {
  id: string;
  title: string;
  snippet: string;
  url?: string | null;
  file_name?: string | null;
  agent?: string | null;
}

export interface AgentStep {
  id: string;
  agent_name: string;
  agent_id?: string | null;
  status: StepStatus;
  input?: string | null;
  output?: string | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  agent_steps: AgentStep[];
  sources: Source[];
}

export interface Health {
  status: string;
  use_mock: boolean;
  live_ready: boolean;
  model_deployment: string;
}
