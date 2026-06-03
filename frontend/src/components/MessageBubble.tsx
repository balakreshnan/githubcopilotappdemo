import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../types";

export function MessageBubble({
  message,
  streaming,
}: {
  message: ChatMessage;
  streaming?: boolean;
}) {
  const isUser = message.role === "user";
  return (
    <div className={`bubble-row ${isUser ? "bubble-row--user" : "bubble-row--assistant"}`}>
      <div className={`bubble ${isUser ? "bubble--user" : "bubble--assistant"}`}>
        <div className="bubble__role">{isUser ? "You" : "RFP Agent"}</div>
        {isUser ? (
          <div className="bubble__text">{message.content}</div>
        ) : (
          <div className="bubble__markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content || ""}
            </ReactMarkdown>
            {streaming && <span className="cursor-blink">▋</span>}
          </div>
        )}
        {!isUser && message.sources.length > 0 && (
          <div className="bubble__source-count">
            {message.sources.length} source{message.sources.length === 1 ? "" : "s"}
          </div>
        )}
      </div>
    </div>
  );
}
