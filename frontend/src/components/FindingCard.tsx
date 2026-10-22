import { useState } from "react";
import type { Finding } from "../types";
import ScoreChart, { fmt, SIGNAL_KEYS, SIGNAL_NAMES, signalBasis } from "./ScoreChart";

const STATUS_LABEL: Record<Finding["eligibility_status"], string> = {
  ranked: "Ranked",
  adequately_covered: "Adequately covered",
  not_prioritized: "Not prioritised for this handoff",
  insufficient: "Insufficient evidence",
  review_required: "Review required",
};

/** The first sentence of the system's interpretation; the rest sits under "Show calculation". */
export function firstSentence(text: string): string {
  const m = text.match(/^.*?[.!?](?=\s|$)/s);
  return (m ? m[0] : text).trim();
}

export default function FindingCard({
  finding,
  selected,
  onSelect,
  selectLabel = "Review with expert",
  onEvidence,
}: {
  finding: Finding;
  selected: boolean;
  onSelect?: () => void;
  selectLabel?: string;
  onEvidence: () => void;
}) {
  const f = finding;
  const [showCalc, setShowCalc] = useState(false);
  const summary = firstSentence(f.summary);
  const calcId = `calc-${f.id}`;

  return (
    <article className={`finding ${selected ? "selected" : ""} status-${f.status}`} aria-label={f.title}>
      <header className="finding-head">
        <div>
          <h3>{f.title}</h3>
          <div className="row gap-s wrap">
            <span className={`elig elig-${f.eligibility_status}`}>{STATUS_LABEL[f.eligibility_status]}</span>
            <span className={`conf conf-${f.evidence_confidence}`}>{f.evidence_confidence} confidence</span>
            {f.status !== "candidate" && <span className={`review review-${f.status}`}>{f.status}</span>}
            {f.prior_knowledge && (
              <span className="review review-confirmed">v{f.prior_knowledge.version_no} already approved</span>
            )}
          </div>
        </div>
        <div className="priority" aria-label="Review priority">
          {f.review_priority === null ? (
            <span className="no-number" title="No number is shown when a gate applies">
              —
            </span>
          ) : (
            <>
              <span className="priority-num">{f.review_priority}</span>
              <span className="priority-label">review priority</span>
            </>
          )}
        </div>
      </header>

      <div className="truth truth-system">System interpretation</div>
      <p className="summary">{summary}</p>
      {f.status_reason && <p className="small muted">Expert note: {f.status_reason}</p>}

      <ScoreChart finding={f} />

      <button
        className="ghost small"
        aria-expanded={showCalc}
        aria-controls={calcId}
        onClick={() => setShowCalc((v) => !v)}
      >
        {showCalc ? "Hide calculation" : "Show calculation"}
      </button>
      {showCalc && (
        <div id={calcId} className="calc">
          {summary !== f.summary && <p className="small">{f.summary}</p>}
          <div className="table-wrap">
            <table className="signals">
              <thead>
                <tr>
                  <th scope="col">Signal</th>
                  <th scope="col">Value</th>
                  <th scope="col">Weight</th>
                  <th scope="col">Points</th>
                  <th scope="col">Basis</th>
                </tr>
              </thead>
              <tbody>
                {SIGNAL_KEYS.map((k) => {
                  const v = f.signals[k];
                  const c = f.contributions[k];
                  return (
                    <tr key={k}>
                      <th scope="row">
                        <span className="sig-key">{k}</span> {SIGNAL_NAMES[k]}
                      </th>
                      <td className="mono">{v === null ? "unknown" : v}</td>
                      <td className="mono">{f.weights[k]}</td>
                      <td className="mono">{c === null ? "—" : fmt(c)}</td>
                      <td className="muted small">{signalBasis(k, f)}</td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row">Raw score</th>
                  <td className="mono" colSpan={4}>
                    {f.raw_score === null ? "not computed" : fmt(f.raw_score)}
                    {f.review_priority !== null && ` → review priority ${f.review_priority}`}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
          {f.reasons.length > 0 && (
            <ul className="reasons">
              {f.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <footer className="row gap-s wrap">
        <button className="secondary" onClick={onEvidence}>
          Inspect {f.evidence_refs.length} citation{f.evidence_refs.length === 1 ? "" : "s"}
        </button>
        {onSelect && (
          <button onClick={onSelect} aria-pressed={selected}>
            {selected ? "Selected for capture" : selectLabel}
          </button>
        )}
      </footer>
    </article>
  );
}
