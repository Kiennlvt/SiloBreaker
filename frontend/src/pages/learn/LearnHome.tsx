import { Link } from "react-router-dom";
import { api } from "../../api";
import ErrorNotice from "../../components/ErrorNotice";
import { useLoad } from "../../hooks";
import type { AggregateResult } from "../../types";

// Labels only; every result comes from the backend.
const RESULT_LABEL: Record<AggregateResult, string> = {
  demonstrated: "Demonstrated",
  partial: "Partially demonstrated",
  not_yet: "Not yet demonstrated",
  review_required: "Waiting for expert review",
};

export default function LearnHome() {
  const { data, error, reload } = useLoad(() => api.myExercises(), []);
  const mine = data?.filter((e) => e.viewer_role === "successor") ?? [];

  return (
    <section className="stack" aria-labelledby="learn-title">
      <h2 id="learn-title">Your exercises</h2>
      <p className="muted">
        Each exercise is built from knowledge an experienced engineer approved. Your answers are kept; you can try again.
      </p>
      <ErrorNotice error={error} onReload={reload} />
      {data && mine.length === 0 && <p className="notice">No exercise has been released to you yet.</p>}
      <ul className="card-list">
        {mine.map((e) => {
          const last = e.latest_attempt;
          const status = !last
            ? "Not started"
            : last.assessment_status === "failed"
              ? "Assessment failed (system error)"
              : last.aggregate_result
                ? RESULT_LABEL[last.aggregate_result]
                : "Assessment pending";
          return (
            <li key={e.id} className="card-row panel">
              <div>
                <strong>{e.title}</strong>
                <span className="muted small">
                  {" "}
                  · {e.project_key} · knowledge v{e.knowledge_version_no}
                </span>
                <p className={`small result-inline result-${last?.aggregate_result ?? "none"}`}>{status}</p>
              </div>
              <Link className="button small" to={`/learn/exercises/${e.id}`}>
                {last ? "Open" : "Start"}
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
