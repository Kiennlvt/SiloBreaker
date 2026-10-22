import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { Chunk, EvidenceRef } from "../types";

const SOURCE_LABEL: Record<string, string> = {
  jira: "Jira",
  slack: "Slack",
  github: "GitHub",
  document: "Runbook",
};

function Highlight({ text, quote }: { text: string; quote: string }) {
  const at = text.indexOf(quote);
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <mark>{quote}</mark>
      {text.slice(at + quote.length)}
    </>
  );
}

export default function EvidenceDrawer({ refs, onClose }: { refs: EvidenceRef[]; onClose: () => void }) {
  const [chunks, setChunks] = useState<Record<string, Chunk | string>>({});

  useEffect(() => {
    let live = true;
    refs.forEach((r) =>
      api
        .chunk(r.chunk_id)
        .then((c) => live && setChunks((m) => ({ ...m, [r.chunk_id]: c })))
        .catch((e: ApiError) => live && setChunks((m) => ({ ...m, [r.chunk_id]: e.message }))),
    );
    return () => {
      live = false;
    };
  }, [refs]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        className="drawer"
        role="dialog"
        aria-label="Source evidence"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="drawer-head">
          <div>
            <span className="truth truth-source">Source observation</span>
            <h2>Cited evidence</h2>
          </div>
          <button className="ghost" onClick={onClose} aria-label="Close evidence">
            Close
          </button>
        </header>
        <p className="muted small">
          Each quote below was checked against the stored text before this finding was shown.
        </p>
        {refs.map((r, i) => {
          const c = chunks[r.chunk_id];
          return (
            <article key={`${r.chunk_id}-${i}`} className="evidence">
              {c === undefined && <p className="muted">Loading…</p>}
              {typeof c === "string" && <p className="error">{c}</p>}
              {c && typeof c !== "string" && (
                <>
                  <div className="evidence-meta">
                    <span className={`src src-${c.item.source}`}>{SOURCE_LABEL[c.item.source] ?? c.item.source}</span>
                    <strong>{c.item.external_id}</strong>
                    <span className="muted">
                      {c.item.author_display_name ?? "no author"}
                      {c.item.occurred_at && ` · ${new Date(c.item.occurred_at).toLocaleDateString()}`}
                      {c.line_start && ` · lines ${c.line_start}–${c.line_end}`}
                    </span>
                    {(r.event || r.document) && <span className="chip">{r.event ?? r.document}</span>}
                  </div>
                  <pre className="evidence-text">
                    <Highlight text={c.text} quote={r.quote} />
                  </pre>
                  {c.item.url && (
                    <a href={c.item.url} target="_blank" rel="noreferrer" className="small">
                      Open in {SOURCE_LABEL[c.item.source] ?? "source"}
                    </a>
                  )}
                </>
              )}
            </article>
          );
        })}
      </aside>
    </div>
  );
}
