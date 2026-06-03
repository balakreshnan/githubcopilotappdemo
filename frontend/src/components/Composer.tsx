import { useState } from "react";

const SUGGESTIONS = [
  "Draft a response to the cloud infrastructure RFP",
  "Summarize the compliance requirements and our coverage",
  "Build a pricing estimate for a 12-month engagement",
];

export function Composer({
  onSend,
  disabled,
}: {
  onSend: (text: string) => void;
  disabled: boolean;
}) {
  const [text, setText] = useState("");

  const send = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
  };

  return (
    <div className="composer">
      <div className="composer__suggestions">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            className="chip"
            disabled={disabled}
            onClick={() => onSend(s)}
          >
            {s}
          </button>
        ))}
      </div>
      <div className="composer__row">
        <textarea
          className="composer__input"
          placeholder="Ask the RFP agent team…"
          value={text}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button className="composer__send" onClick={send} disabled={disabled || !text.trim()}>
          {disabled ? "Working…" : "Send"}
        </button>
      </div>
    </div>
  );
}
