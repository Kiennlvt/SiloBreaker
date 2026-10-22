import type { Finding, SignalKey } from "../types";

// Draws the backend's score breakdown. Every number (weights, contributions, cap, raw score,
// priority) comes from the API; nothing is computed or re-derived here.

export const SIGNAL_KEYS: SignalKey[] = ["A", "D", "O", "M", "B"];

export const SIGNAL_NAMES: Record<SignalKey, string> = {
  A: "Operational repetition",
  D: "Documentation gap",
  O: "Selected engineer participation",
  M: "Manual intervention",
  B: "Limited alternate recovery",
};

const NO_PRIORITY: Record<Finding["eligibility_status"], string> = {
  ranked: "",
  adequately_covered: "Supplied documentation already covers this area.",
  not_prioritized: "The selected engineer handled under half of the events.",
  insufficient: "There is not enough evidence to show a number.",
  review_required: "The evidence contradicts itself and needs a human look.",
};

/** Short, plain-language basis for one signal, from the backend's counts. */
export function signalBasis(key: SignalKey, f: Finding): string {
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
}

export function fmt(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

/** Capped means the backend lowered the priority to the cap and said why. */
export function isCapped(f: Finding): boolean {
  return f.eligibility_status === "ranked" && f.reasons.some((r) => r.startsWith("Capped"));
}

export default function ScoreChart({ finding: f }: { finding: Finding }) {
  const ranked = f.eligibility_status === "ranked" && f.review_priority !== null;
  const capped = isCapped(f);
  const maxWeight = Math.max(...SIGNAL_KEYS.map((k) => f.weights[k]));
  let offset = 0;

  const totalLabel = ranked
    ? `Raw score ${fmt(f.raw_score ?? 0)} of 100, review priority ${f.review_priority}${capped ? `, capped at ${f.cap}` : ""}`
    : "";

  return (
    <div className="score-chart">
      {ranked ? (
        <div className="total">
          <p className="total-label">
            <span>
              Raw <strong>{fmt(f.raw_score ?? 0)}</strong> → priority <strong>{f.review_priority}</strong>
            </span>
            <span className="muted small">scale 0–100</span>
          </p>
          <svg
            className="bar total-bar"
            viewBox="0 0 100 10"
            preserveAspectRatio="none"
            role="img"
            aria-label={totalLabel}
          >
            <rect className="track" x={0} y={0} width={100} height={10} />
            {SIGNAL_KEYS.map((k) => {
              const v = f.contributions[k] ?? 0;
              const x = offset;
              offset += v;
              return v > 0 ? <rect key={k} className={`seg seg-${k}`} x={x} y={0} width={v} height={10} /> : null;
            })}
            {capped && (
              <line
                data-testid="cap-line"
                className="cap-line"
                x1={f.cap}
                x2={f.cap}
                y1={-1}
                y2={11}
                vectorEffect="non-scaling-stroke"
              />
            )}
          </svg>
          {capped && (
            <div className="cap-note">
              <strong>Capped at {f.cap}</strong>
              <ul>
                {f.reasons.map((r) => (
                  <li key={r}>{r.replace(/^Capped:\s*/, "")}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <div className="no-priority" role="note">
          <strong>No priority shown</strong>
          <span className="muted small">{f.reasons[0] ?? NO_PRIORITY[f.eligibility_status]}</span>
        </div>
      )}

      <ul className="signal-bars">
        {SIGNAL_KEYS.map((k) => {
          const w = f.weights[k];
          const v = f.contributions[k];
          const label =
            v === null
              ? `${k} ${SIGNAL_NAMES[k]}: unknown, up to ${w} points`
              : `${k} ${SIGNAL_NAMES[k]}: ${fmt(v)} of ${w} points`;
          return (
            <li key={k} className={v === null ? "signal unknown" : "signal"}>
              <div className="signal-head">
                <span>
                  <span className="sig-key">{k}</span> {SIGNAL_NAMES[k]}
                </span>
                <span className="mono">{v === null ? `unknown / ${w}` : `${fmt(v)} / ${w}`}</span>
              </div>
              <svg
                className="bar signal-bar"
                viewBox={`0 0 ${maxWeight} 6`}
                preserveAspectRatio="none"
                role="img"
                aria-label={label}
              >
                <rect
                  className={v === null ? "track track-unknown" : "track"}
                  x={0}
                  y={0}
                  width={w}
                  height={6}
                  vectorEffect="non-scaling-stroke"
                />
                {v !== null && v > 0 && <rect className={`seg seg-${k}`} x={0} y={0} width={v} height={6} />}
              </svg>
              <span className="muted small basis">{signalBasis(k, f)}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
