import { useState } from "react";

const SUGGESTIONS = [
  "Summarize the Virginia Railway Express project RFP with details",
  "Summarize the scope of work for the Connecticut Department of Transportation project RFP",
  "Summarize the RFP for fiber network construction for Holy Cross Energy",
  "Summarize the Request for Qualification for the Moscone Expansion Project construction management support services",
  "Summarize the RFP for US Department of Transportation project management oversight",
  "Summarize the RFP for construction engineering inspection services for Bristol District",
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
