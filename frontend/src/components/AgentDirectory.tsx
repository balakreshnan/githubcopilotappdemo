import type { AgentInfo } from "../types";

export function AgentDirectory({ agents }: { agents: AgentInfo[] }) {
  const main = agents.find((a) => a.role === "main");
  const connected = agents.filter((a) => a.role === "connected");

  return (
    <aside className="sidebar">
      <div className="sidebar-title">Agent Team</div>
      {main && (
        <div className="agent-card agent-card--main">
          <div className="agent-card__badge">Orchestrator</div>
          <div className="agent-card__name">{main.name}</div>
          <div className="agent-card__desc">{main.description}</div>
        </div>
      )}
      <div className="sidebar-subtitle">Specialists ({connected.length})</div>
      {connected.map((a) => (
        <div key={a.id} className="agent-card">
          <div className="agent-card__name">{a.name}</div>
          <div className="agent-card__desc">{a.description}</div>
        </div>
      ))}
    </aside>
  );
}
