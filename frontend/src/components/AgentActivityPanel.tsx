import type { AgentStep } from "../types";

function StatusDot({ status }: { status: AgentStep["status"] }) {
  return <span className={`status-dot status-dot--${status}`} title={status} />;
}

export function AgentActivityPanel({ steps }: { steps: AgentStep[] }) {
  if (steps.length === 0) {
    return (
      <div className="panel-empty">
        Agent activity will appear here as each specialist works.
      </div>
    );
  }

  return (
    <div className="activity-list">
      {steps.map((step) => (
        <div key={step.id} className={`activity-card activity-card--${step.status}`}>
          <div className="activity-card__head">
            <StatusDot status={step.status} />
            <span className="activity-card__name">{step.agent_name}</span>
            <span className="activity-card__status">
              {step.status === "running" ? "working…" : step.status}
            </span>
          </div>
          {step.output ? (
            <div className="activity-card__output">{step.output}</div>
          ) : step.status === "running" ? (
            <div className="activity-card__output activity-card__output--muted">
              Analyzing the request…
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}
