import { useEffect, useMemo, useRef, useState } from "react";
import { getAgents, getHealth, streamChat } from "./api";
import type { AgentInfo, AgentStep, ChatMessage, Health, Source } from "./types";
import { AgentDirectory } from "./components/AgentDirectory";
import { AgentActivityPanel } from "./components/AgentActivityPanel";
import { SourcesPanel } from "./components/SourcesPanel";
import { MessageBubble } from "./components/MessageBubble";
import { Composer } from "./components/Composer";

type RightTab = "activity" | "sources";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [rightTab, setRightTab] = useState<RightTab>("activity");

  // Live streaming state for the in-flight turn.
  const [streaming, setStreaming] = useState(false);
  const [liveSteps, setLiveSteps] = useState<AgentStep[]>([]);
  const [liveText, setLiveText] = useState("");
  const [liveSources, setLiveSources] = useState<Source[]>([]);

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setError("Backend not reachable."));
    getAgents().then(setAgents).catch(() => {});
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, liveText, liveSteps]);

  const lastAssistant = useMemo(
    () => [...messages].reverse().find((m) => m.role === "assistant"),
    [messages],
  );

  const activeSteps = streaming ? liveSteps : lastAssistant?.agent_steps ?? [];
  const activeSources = streaming ? liveSources : lastAssistant?.sources ?? [];

  const send = (text: string) => {
    if (streaming) return;
    setError(null);
    setMessages((m) => [...m, { role: "user", content: text, agent_steps: [], sources: [] }]);
    setLiveSteps([]);
    setLiveText("");
    setLiveSources([]);
    setStreaming(true);
    setRightTab("activity");

    streamChat(threadId, text, {
      onThread: (id) => setThreadId(id),
      onAgentStep: (step) =>
        setLiveSteps((prev) => {
          const idx = prev.findIndex((s) => s.id === step.id);
          if (idx === -1) return [...prev, step];
          const next = [...prev];
          next[idx] = step;
          return next;
        }),
      onToken: (t) => setLiveText((prev) => prev + t),
      onSources: (s) => {
        setLiveSources(s);
        setRightTab("sources");
      },
      onDone: (msg) => {
        const finalMsg: ChatMessage = {
          ...msg,
          agent_steps: msg.agent_steps.length ? msg.agent_steps : liveStepsRef.current,
          sources: msg.sources.length ? msg.sources : liveSourcesRef.current,
        };
        setMessages((m) => [...m, finalMsg]);
        setStreaming(false);
        setLiveText("");
      },
      onError: (m) => {
        setError(m);
        setStreaming(false);
      },
    });
  };

  // Refs so onDone can read the latest live values without stale closures.
  const liveStepsRef = useRef<AgentStep[]>([]);
  const liveSourcesRef = useRef<Source[]>([]);
  liveStepsRef.current = liveSteps;
  liveSourcesRef.current = liveSources;

  const runningCount = activeSteps.filter((s) => s.status === "running").length;

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar__brand">
          <span className="topbar__logo">◆</span>
          <span className="topbar__title">RFP Agent Studio</span>
          <span className="topbar__subtitle">Microsoft Foundry multi-agent workspace</span>
        </div>
        <div className="topbar__status">
          {health?.model_deployment && (
            <span className="pill pill--model">{health.model_deployment}</span>
          )}
          <span className={`pill ${health?.live_ready ? "pill--live" : "pill--mock"}`}>
            {health ? (health.live_ready ? "Live Foundry" : "Mock mode") : "…"}
          </span>
        </div>
      </header>

      <div className="layout">
        <AgentDirectory agents={agents} />

        <main className="chat">
          <div className="chat__scroll" ref={scrollRef}>
            {messages.length === 0 && !streaming && (
              <div className="welcome">
                <h1>Respond to RFPs with your agent team</h1>
                <p>
                  Ask a question and watch the orchestrator delegate to specialized
                  agents. Each agent's output and its sources are shown on the right.
                </p>
              </div>
            )}

            {messages.map((m, i) => (
              <MessageBubble key={i} message={m} />
            ))}

            {streaming && (
              <MessageBubble
                message={{ role: "assistant", content: liveText, agent_steps: [], sources: [] }}
                streaming
              />
            )}

            {error && <div className="error-banner">{error}</div>}
          </div>

          <Composer onSend={send} disabled={streaming} />
        </main>

        <section className="rightpanel">
          <div className="rightpanel__tabs">
            <button
              className={`tab ${rightTab === "activity" ? "tab--active" : ""}`}
              onClick={() => setRightTab("activity")}
            >
              Agent Activity
              {runningCount > 0 && <span className="tab__badge">{runningCount}</span>}
            </button>
            <button
              className={`tab ${rightTab === "sources" ? "tab--active" : ""}`}
              onClick={() => setRightTab("sources")}
            >
              Sources
              {activeSources.length > 0 && (
                <span className="tab__badge">{activeSources.length}</span>
              )}
            </button>
          </div>
          <div className="rightpanel__body">
            {rightTab === "activity" ? (
              <AgentActivityPanel steps={activeSteps} />
            ) : (
              <SourcesPanel sources={activeSources} />
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
