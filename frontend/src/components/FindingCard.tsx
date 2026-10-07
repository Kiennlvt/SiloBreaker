import type { Finding } from "../types";

const SIGNAL_NAMES: Record<string, string> = {
  A: "Operational repetition",
  D: "Documentation gap",
  O: "Selected engineer participation",
  M: "Manual intervention",
  B: "Limited alternate recovery",
};
const WEIGHTS: Record<string, number> = { A: 25, D: 25, O: 20, M: 15, B: 15 };

const STATUS_LABEL: Record<Finding["eligibility_status"], string> = {
  ranked: "Ranked",
  adequately_covered: "Adequately covered",
  not_prioritized: "Not prioritised for this handoff",
  insufficient: "Insufficient evidence",
  review_required: "Review required",
};

function signalDetail(key: string, f: Finding): string {
  const c = f.counts;
  switch (key) {
    case "A":
      return `${c.distinct_events} distinct event(s)`;
    case "D":
      return f.signals.D === null
        ? "docs not imported"
        : c.relevant_documents
          ? f.missing_facets.length
            ? `missing: ${f.missing_facets.map((m) => m.replace(/_/g, " ")).join(", ")}`
            : "all facets covered"
          : "no procedure found";
    case "O":
      return c.participation_share === null
        ? `${c.attributable_events} attributable, too few`
        : `${c.events_by_selected} of ${c.attributable_events} events`;
    case "M":
      return `${c.manual_events} manual event(s)`;
    case "B":
      return c.participation_share === null ? "unknown" : `${c.events_by_others} by others`;
  }
  return "";
}

export default function FindingCard({
  finding,
  selected,
  onSelect,
  onEvidence,
}: {
  finding: Finding;
  selected: boolean;
  onSelect?: () => void;
  onEvidence: () => void;
}) {
  const f = finding;
  return (
    <article className={`finding ${selected ? "selected" : ""} status-${f.status}`}>
      <header className="finding-head">
        <div>
          <h3>{f.title}</h3>
          <div className="row gap-s wrap">
            <span className={`elig elig-${f.eligibility_status}`}>{STATUS_LABEL[f.eligibility_status]}</span>
            <span className={`conf conf-${f.evidence_confidence}`}>{f.evidence_confidence} confidence</span>
            {f.status !== "candidate" && <span className={`review review-${f.status}`}>{f.status}</span>}
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
      <p className="summary">{f.summary}</p>
      {f.status_reason && <p className="small muted">Expert note: {f.status_reason}</p>}

      <table className="signals">
        <thead>
          <tr>
            <th scope="col">Signal</th>
            <th scope="col">Value</th>
            <th scope="col">× weight</th>
            <th scope="col">Basis</th>
          </tr>
        </thead>
        <tbody>
          {Object.keys(SIGNAL_NAMES).map((k) => {
            const v = f.signals[k as keyof Finding["signals"]];
            return (
              <tr key={k}>
                <th scope="row">
                  <span className="sig-key">{k}</span> {SIGNAL_NAMES[k]}
                </th>
                <td className="mono">{v === null ? "unknown" : v}</td>
                <td className="mono">{v === null ? "—" : WEIGHTS[k] * v}</td>
                <td className="muted small">{signalDetail(k, f)}</td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">Raw score</th>
            <td className="mono" colSpan={3}>
              {f.raw_score ?? "not computed"}
            </td>
          </tr>
        </tfoot>
      </table>
      {f.reasons.length > 0 && (
        <ul className="reasons">
          {f.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      <footer className="row gap-s">
        <button className="secondary" onClick={onEvidence}>
          Inspect {f.evidence_refs.length} citation{f.evidence_refs.length === 1 ? "" : "s"}
        </button>
        {onSelect && (
          <button onClick={onSelect} aria-pressed={selected}>
            {selected ? "Selected for capture" : "Review with expert"}
          </button>
        )}
      </footer>
    </article>
  );
}
