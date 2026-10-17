import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { AggregateResult, Attempt, Criterion, Exercise, Verdict } from "../types";
import ErrorNotice from "./ErrorNotice";

// Labels only. Every verdict and result comes from the backend; nothing is scored here.
const RESULT_LABEL: Record<AggregateResult, string> = {
  demonstrated: "Demonstrated in this exercise",
  partial: "Partially demonstrated",
  not_yet: "Not yet demonstrated",
  review_required: "Review required by the expert",
};
const VERDICT_LABEL: Record<Verdict, string> = {
  met: "Met",
  partial: "Partly met",
  unmet: "Not met",
  uncertain: "Unclear",
};

type Role = "expert" | "successor";

export type VerifyPanelProps = {
  versionId: string;
  versionNo: number;
  expertId: string;
  successorId: string;
  initialRole?: Role;
};

export default function VerifyPanel({ versionId, versionNo, expertId, successorId, initialRole = "expert" }: VerifyPanelProps) {
  const [role, setRole] = useState<Role>(initialRole);
  const viewer = role === "expert" ? expertId : successorId;
  const [exercise, setExercise] = useState<Exercise | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    const list = await api.listExercises(versionId, viewer);
    setExercise(list.length ? list[list.length - 1] : null);
    setLoaded(true);
  }, [versionId, viewer]);

  useEffect(() => {
    setLoaded(false);
    setExercise(null);
    setError(null);
    load().catch(setError);
  }, [load]);

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e);
      // A provider failure still stored the attempt; reload so it appears as failed.
      if (e instanceof ApiError && e.extra.attempt_id) await load().catch(() => undefined);
    } finally {
      setBusy(null);
    }
  };

  const reload = () => {
    setError(null);
    load().catch(setError);
  };

  return (
    <section className="panel verify" aria-labelledby="verify-title">
      <header className="panel-head">
        <div>
          <p className="eyebrow">Step 3 · Verify</p>
          <h2 id="verify-title">Exercise for knowledge v{versionNo}</h2>
        </div>
        <fieldset className="role-switch">
          <legend className="visually-hidden">View as</legend>
          <label>
            <input type="radio" name="verify-role" checked={role === "expert"} onChange={() => setRole("expert")} />
            Expert ({expertId})
          </label>
          <label>
            <input
              type="radio"
              name="verify-role"
              checked={role === "successor"}
              onChange={() => setRole("successor")}
            />
            Successor ({successorId})
          </label>
        </fieldset>
      </header>

      <ErrorNotice error={error} onReload={reload} />
      {busy && (
        <p className="busy" role="status">
          {busy}…
        </p>
      )}
      {!loaded && !error && <p role="status">Loading exercise…</p>}

      {loaded && role === "expert" && (
        <ExpertView
          exercise={exercise}
          busy={!!busy}
          onGenerate={() => run("Generating exercise", () => api.createExercise(versionId, expertId))}
          onSave={(scenario, criteria) =>
            run("Saving exercise", () =>
              api.saveExerciseDraft(exercise!.id, {
                scenario,
                criteria,
                expected_revision: exercise!.revision!,
                actor_id: expertId,
              }),
            )
          }
          onApprove={() =>
            run("Releasing exercise", () =>
              api.approveExercise(exercise!.id, { expected_revision: exercise!.revision!, actor_id: expertId }),
            )
          }
        />
      )}

      {loaded && role === "successor" && (
        <SuccessorView
          exercise={exercise}
          busy={!!busy}
          onSubmit={(answer) =>
            run("Assessing your answer", () => api.submitAttempt(exercise!.id, { actor_id: successorId, answer }))
          }
          onReassess={(attemptId) => run("Re-assessing", () => api.reassess(attemptId, successorId))}
        />
      )}
    </section>
  );
}

function ExpertView({
  exercise,
  busy,
  onGenerate,
  onSave,
  onApprove,
}: {
  exercise: Exercise | null;
  busy: boolean;
  onGenerate: () => void;
  onSave: (scenario: string, criteria: Criterion[]) => void;
  onApprove: () => void;
}) {
  const [scenario, setScenario] = useState("");
  const [criteria, setCriteria] = useState<Criterion[]>([]);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setScenario(exercise?.scenario ?? "");
    setCriteria(exercise?.criteria ?? []);
    setDirty(false);
  }, [exercise]);

  if (!exercise)
    return (
      <div className="stack">
        <p className="notice">No exercise exists for this approved version yet.</p>
        <button disabled={busy} onClick={onGenerate}>
          Generate exercise
        </button>
      </div>
    );

  const editable = exercise.status === "draft";
  const patch = (i: number, p: Partial<Criterion>) => {
    setCriteria((cs) => cs.map((c, j) => (j === i ? { ...c, ...p } : c)));
    setDirty(true);
  };

  return (
    <div className="stack">
      <p className="muted small">
        Status: <strong>{exercise.status === "ready" ? "released" : exercise.status}</strong> · revision{" "}
        {exercise.revision} · generated by {exercise.generator_id}
        {exercise.approved_by && ` · released by ${exercise.approved_by}`}
      </p>
      <label className="field">
        <span>Scenario (visible to the successor)</span>
        <textarea
          rows={4}
          value={scenario}
          readOnly={!editable}
          onChange={(e) => {
            setScenario(e.target.value);
            setDirty(true);
          }}
        />
      </label>
      <fieldset className="list-editor">
        <legend>Private rubric (never shown to the successor before assessment)</legend>
        {criteria.map((c, i) => (
          <div key={c.id} className="criterion">
            <label className="field">
              <span>
                {c.id} · from <code>{c.source_path}</code>
              </span>
              <textarea
                rows={2}
                value={c.text}
                readOnly={!editable}
                onChange={(e) => patch(i, { text: e.target.value })}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={c.critical}
                disabled={!editable}
                onChange={(e) => patch(i, { critical: e.target.checked })}
              />
              Critical: missing it blocks “demonstrated”
            </label>
          </div>
        ))}
      </fieldset>
      {editable && (
        <div className="row gap-s wrap">
          <button className="secondary" disabled={busy || !dirty} onClick={() => onSave(scenario, criteria)}>
            Save exercise draft
          </button>
          <button
            disabled={busy || dirty}
            title={dirty ? "Save first; release names an exact revision" : undefined}
            onClick={onApprove}
          >
            Approve and release exercise
          </button>
        </div>
      )}
      {exercise.attempts.length > 0 && (
        <div className="attempts">
          <h3>Successor attempts</h3>
          {exercise.attempts.map((a, i) => (
            <AttemptCard key={a.id} attempt={a} index={i + 1} showCritical />
          ))}
        </div>
      )}
    </div>
  );
}

function SuccessorView({
  exercise,
  busy,
  onSubmit,
  onReassess,
}: {
  exercise: Exercise | null;
  busy: boolean;
  onSubmit: (answer: string) => void;
  onReassess: (attemptId: string) => void;
}) {
  const [answer, setAnswer] = useState("");
  const [answering, setAnswering] = useState(true);
  const attempts = exercise?.attempts ?? [];
  const last: Attempt | undefined = attempts[attempts.length - 1];

  useEffect(() => {
    // Show the form until there is an attempt; afterwards show its result first.
    setAnswering(attempts.length === 0);
    setAnswer("");
  }, [exercise?.id, attempts.length]);

  if (!exercise) return <p className="notice">The expert has not released an exercise yet.</p>;

  return (
    <div className="stack">
      <blockquote className="question">
        <span className="truth truth-system">Scenario</span>
        {exercise.scenario}
      </blockquote>
      {answering ? (
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            if (answer.trim()) onSubmit(answer);
          }}
        >
          <label className="field">
            <span>Your answer</span>
            <textarea rows={6} value={answer} onChange={(e) => setAnswer(e.target.value)} />
          </label>
          <button type="submit" disabled={busy || !answer.trim()}>
            Submit answer
          </button>
        </form>
      ) : (
        last && (
          <>
            <AttemptCard attempt={last} index={attempts.length} />
            {last.assessment_status === "failed" ? (
              <button className="secondary" disabled={busy} onClick={() => onReassess(last.id)}>
                Assess again
              </button>
            ) : (
              <button className="secondary" disabled={busy} onClick={() => setAnswering(true)}>
                Try again
              </button>
            )}
          </>
        )
      )}
      {attempts.length > 1 && (
        <details className="controls">
          <summary>Earlier attempts ({attempts.length - 1})</summary>
          {attempts.slice(0, -1).map((a, i) => (
            <AttemptCard key={a.id} attempt={a} index={i + 1} />
          ))}
        </details>
      )}
    </div>
  );
}

function AttemptCard({ attempt: a, index, showCritical = false }: { attempt: Attempt; index: number; showCritical?: boolean }) {
  return (
    <article className="attempt" aria-label={`Attempt ${index}`}>
      <header className="row between wrap">
        <strong>Attempt {index}</strong>
        <span className="muted small">
          on knowledge v{a.knowledge_version_no} · {new Date(a.created_at).toLocaleString()}
        </span>
      </header>
      {a.assessment_status === "pending" && <p role="status">Assessment pending…</p>}
      {a.assessment_status === "failed" && (
        <p className="error error-provider" role="alert">
          Assessment failed because of a system error ({a.assessment_error}). Your answer is saved; this is not a result.
        </p>
      )}
      {a.aggregate_result && (
        <p className={`result result-${a.aggregate_result}`} role="status">
          {RESULT_LABEL[a.aggregate_result]}
        </p>
      )}
      {a.results && (
        <ul className="criteria-results">
          {a.results.map((r) => (
            <li key={r.criterion_id} className={`verdict verdict-${r.verdict}`}>
              <span className="verdict-label">{VERDICT_LABEL[r.verdict]}</span> {r.text}
              {showCritical && r.critical && <span className="chip">critical</span>}
              {r.evidence_quote && <q className="muted small">{r.evidence_quote}</q>}
            </li>
          ))}
        </ul>
      )}
      <details>
        <summary>Answer</summary>
        <p className="answer">{a.answer}</p>
      </details>
    </article>
  );
}
