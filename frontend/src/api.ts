import type { AgentInfo, AgentStep, ChatMessage, Health, Source } from "./types";

const BASE = "/api";

export async function getHealth(): Promise<Health> {
  const res = await fetch(`${BASE}/health`);
  if (!res.ok) throw new Error(`health failed: ${res.status}`);
  return res.json();
}

export async function getAgents(): Promise<AgentInfo[]> {
  const res = await fetch(`${BASE}/agents`);
  if (!res.ok) throw new Error(`agents failed: ${res.status}`);
  return res.json();
}

export interface StreamHandlers {
  onThread?: (threadId: string) => void;
  onAgentStep?: (step: AgentStep) => void;
  onToken?: (text: string) => void;
  onSources?: (sources: Source[]) => void;
  onDone?: (message: ChatMessage) => void;
  onError?: (message: string) => void;
}

/**
 * Stream a chat turn. The backend responds with SSE over a POST request, so we
 * read the response body and parse SSE frames manually (EventSource can't POST).
 */
export async function streamChat(
  threadId: string | null,
  message: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, message }),
    signal,
  });

  if (!res.ok || !res.body) {
    handlers.onError?.(`chat failed: ${res.status}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      dispatchFrame(frame, handlers);
    }
  }
}

function dispatchFrame(frame: string, handlers: StreamHandlers): void {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return;

  let data: unknown;
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch {
    return;
  }

  switch (event) {
    case "thread":
      handlers.onThread?.((data as { thread_id: string }).thread_id);
      break;
    case "agent_step":
      handlers.onAgentStep?.(data as AgentStep);
      break;
    case "token":
      handlers.onToken?.((data as { text: string }).text);
      break;
    case "sources":
      handlers.onSources?.(data as Source[]);
      break;
    case "done":
      handlers.onDone?.((data as { message: ChatMessage }).message);
      break;
    case "error":
      handlers.onError?.((data as { message: string }).message);
      break;
  }
}
