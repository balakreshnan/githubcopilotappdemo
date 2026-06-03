import type { Source } from "../types";

export function SourcesPanel({ sources }: { sources: Source[] }) {
  if (sources.length === 0) {
    return (
      <div className="panel-empty">
        Citations and source documents will be listed here.
      </div>
    );
  }

  return (
    <div className="sources-list">
      {sources.map((s, i) => (
        <div key={s.id} className="source-card">
          <div className="source-card__head">
            <span className="source-card__index">{i + 1}</span>
            <span className="source-card__title">{s.title}</span>
          </div>
          {s.snippet && <div className="source-card__snippet">“{s.snippet}”</div>}
          <div className="source-card__meta">
            {s.agent && <span className="source-card__agent">{s.agent}</span>}
            {s.file_name && <span className="source-card__file">{s.file_name}</span>}
            {s.url && (
              <a
                className="source-card__link"
                href={s.url}
                target="_blank"
                rel="noreferrer"
              >
                Open ↗
              </a>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
