import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { FindingDetail, KnowledgeContent, KnowledgeVersion } from "../types";
import ListEditor from "./ListEditor";

const EMPTY: KnowledgeContent = {
  applicability: "",
  prerequisites: [],
  steps: [],
  stop_and_escalate: [],
  success_checks: [],
  limitations: [],
  unresolved: [],
};

function clean(c: KnowledgeContent): KnowledgeContent {
  const f = (xs: string[]) => xs.map((x) => x.trim()).filter(Boolean);
  return {
    applicability: c.applicability.trim(),
    prerequisites: f(c.prerequisites),
    steps: f(c.steps),
    stop_and_escalate: f(c.stop_and_escalate),
    success_checks: f(c.success_checks),
    limitations: f(c.limitations),
    unresolved: f(c.unresolved),
  };
}

export default function CapturePanel({ findingId, onChanged }: { findingId: string; onChanged: () => void }) {
  const [detail, setDetail] = useState<FindingDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [answer, setAnswer] = useState("");
  const [content, setContent] = useState<KnowledgeContent>(EMPTY);
  const [dirty, setDirty] = useState(false);
  const [okf, setOkf] = useState<{ version: KnowledgeVersion; text: string } | null>(null);

  const load = useCallback(async () => {
    const d = await api.finding(findingId);
    setDetail(d);
    if (d.draft) {
      setContent(d.draft.content);
      setDirty(false);
    }
    return d;
  }, [findingId]);

  useEffect(() => {
    setDetail(null);
    setOkf(null);
    setAnswer("");
    setReason("");
    setContent(EMPTY);
    load().catch((e: ApiError) => setError(e.message));
  }, [load]);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? `${e.message} (${e.code})` : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!detail) return <section className="panel">{error ? <p className="error">{error}</p> : <p>Loading…</p>}</section>;

  const expert = detail.handoff.expert_id;
  const edit = (patch: Partial<KnowledgeContent>) => {
    setContent((c) => ({ ...c, ...patch }));
    setDirty(true);
  };
  const review = (action: string) =>
    run(() => api.review(detail.id, { action, reason, expected_revision: detail.revision, actor_id: expert }));
  const latest = detail.versions[detail.versions.length - 1];
  const draftPublished = latest && detail.draft && latest.draft_revision === detail.draft.revision && !dirty;

  return (
    <section className="panel capture" aria-labelledby="capture-title">
      <header className="panel-head">
        <div>
          <p className="eyebrow">Step 2 · Capture</p>
          <h2 id="capture-title">{detail.title}</h2>
        </div>
        <span className="acting">Acting as {expert} (experienced engineer)</span>
      </header>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {detail.status === "candidate" && (
        <div className="stack">
          <p>
            Does this candidate describe a real gap? Confirming records your judgement only; it publishes nothing.
          </p>
          <label className="field">
            <span>Reason (required to correct, reject or mark obsolete)</span>
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <div className="row gap-s wrap">
            <button disabled={busy} onClick={() => review("confirm")}>
              Confirm
            </button>
            <button className="secondary" disabled={busy} onClick={() => review("correct")}>
              Confirm with correction
            </button>
            <button className="danger" disabled={busy} onClick={() => review("reject")}>
              Reject
            </button>
            <button className="ghost" disabled={busy} onClick={() => review("obsolete")}>
              Mark obsolete
            </button>
          </div>
        </div>
      )}

      {(detail.status === "rejected" || detail.status === "obsolete") && (
        <p className="notice">
          This finding was {detail.status}. It cannot become knowledge. {detail.status_reason && `Reason: ${detail.status_reason}`}
        </p>
      )}

      {detail.status === "confirmed" && (
        <div className="stack">
          {detail.question && (
            <blockquote className="question">
              <span className="truth truth-system">Targeted question</span>
              {detail.question}
            </blockquote>
          )}
          <label className="field">
            <span>Expert answer, in your own words</span>
            <textarea rows={5} value={answer} onChange={(e) => setAnswer(e.target.value)} />
          </label>
          <div className="row gap-s">
            <button
              className="secondary"
              disabled={busy || !answer.trim()}
              onClick={() =>
                run(async () => {
                  const s = await api.structure(detail.id, answer);
                  setContent(s);
                  setDirty(true);
                })
              }
            >
              Structure my answer
            </button>
            <span className="muted small">Only your sentences are reorganised. Nothing is added or saved.</span>
          </div>

          <div className="draft">
            <div className="row between">
              <h3>Knowledge Unit draft</h3>
              <span className="muted small">
                {detail.draft ? `Saved revision ${detail.draft.revision}` : "Not saved yet"}
                {dirty && " · unsaved changes"}
              </span>
            </div>
            <label className="field">
              <span>Applicability</span>
              <input value={content.applicability} onChange={(e) => edit({ applicability: e.target.value })} />
            </label>
            <ListEditor label="Preconditions" items={content.prerequisites} onChange={(v) => edit({ prerequisites: v })} />
            <ListEditor label="Ordered steps" ordered items={content.steps} onChange={(v) => edit({ steps: v })} />
            <ListEditor
              label="Stop and escalate"
              hint="Conditions under which the successor must not continue."
              items={content.stop_and_escalate}
              onChange={(v) => edit({ stop_and_escalate: v })}
            />
            <ListEditor label="Success checks" items={content.success_checks} onChange={(v) => edit({ success_checks: v })} />
            <ListEditor label="Limitations" items={content.limitations} onChange={(v) => edit({ limitations: v })} />
            <ListEditor
              label="Unresolved details"
              hint="Unknowns stay here instead of being guessed."
              items={content.unresolved}
              onChange={(v) => edit({ unresolved: v })}
            />
            <div className="row gap-s wrap">
              <button
                className="secondary"
                disabled={busy || !dirty}
                onClick={() =>
                  run(() =>
                    api.saveDraft(detail.id, {
                      content: clean(content),
                      expected_revision: detail.draft?.revision ?? null,
                      author_id: expert,
                    }),
                  )
                }
              >
                Save draft
              </button>
              <button
                disabled={busy || !detail.draft || dirty || !!draftPublished}
                title={dirty ? "Save the draft first; approval names an exact saved revision" : undefined}
                onClick={() =>
                  run(() =>
                    api.publish(detail.id, {
                      expected_finding_revision: detail.revision,
                      draft_revision: detail.draft!.revision,
                      approver_id: expert,
                    }),
                  )
                }
              >
                {detail.draft ? `Approve revision ${detail.draft.revision}` : "Approve"}
              </button>
            </div>
          </div>
        </div>
      )}

      {detail.versions.length > 0 && (
        <div className="versions">
          <span className="truth truth-human">Human-approved knowledge</span>
          <h3>Approved versions</h3>
          <ul>
            {[...detail.versions].reverse().map((v) => (
              <li key={v.id} className="row between wrap">
                <span>
                  <strong>v{v.version_no}</strong> · draft rev {v.draft_revision} · approved by {v.approved_by} on{" "}
                  {new Date(v.approved_at).toLocaleString()}
                  {v.supersedes_version_id && " · supersedes previous"}
                </span>
                <button
                  className="ghost small"
                  onClick={() => run(async () => setOkf({ version: v, text: await api.okf(v.id) }))}
                >
                  View OKF export
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {okf && (
        <div className="okf">
          <div className="row between">
            <h3>
              OKF export · {detail.area_key}-v{okf.version.version_no}.md
            </h3>
            <a
              className="button secondary small"
              download={`${detail.area_key}-v${okf.version.version_no}.md`}
              href={URL.createObjectURL(new Blob([okf.text], { type: "text/markdown" }))}
            >
              Download
            </a>
          </div>
          <pre>{okf.text}</pre>
        </div>
      )}
    </section>
  );
}
