import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import CapturePanel, { type VerifyTarget } from "./components/CapturePanel";
import ErrorNotice from "./components/ErrorNotice";
import EvidenceDrawer from "./components/EvidenceDrawer";
import FindingCard from "./components/FindingCard";
import VerifyPanel from "./components/VerifyPanel";
import type { Analysis, Bundle, EvidenceRef, Handoff } from "./types";

export default function App() {
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [handoff, setHandoff] = useState<Handoff | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [expert, setExpert] = useState("alice");
  const [successor, setSuccessor] = useState("bob");
  const [selectedEngineer, setSelectedEngineer] = useState("alice");
  const [focus, setFocus] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<EvidenceRef[] | null>(null);
  const [verifyTarget, setVerifyTarget] = useState<VerifyTarget>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    api
      .importBundle()
      .then(setBundle)
      .catch(setError);
  }, []);

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };

  const reset = () =>
    run("Resetting demo", async () => {
      setBundle(await api.reset());
      setHandoff(null);
      setAnalysis(null);
      setFocus(null);
      setVerifyTarget(null);
    });

  const start = () =>
    run("Creating handoff", async () => {
      const h = await api.createHandoff({ bundle_id: bundle!.id, expert_id: expert, successor_id: successor });
      setHandoff(h);
      setSelectedEngineer(h.expert_id);
      setAnalysis(await api.analyze(h.id, h.expert_id));
      setFocus(null);
    });

  const reanalyze = (who: string) =>
    run("Analysing", async () => {
      setSelectedEngineer(who);
      setAnalysis(await api.analyze(handoff!.id, who));
      setFocus(null);
    });

  const refreshAnalysis = async () => {
    if (!analysis) return;
    // Findings changed status; refetch the same snapshot rather than re-analysing.
    setAnalysis(await api.getAnalysis(analysis.id));
  };

  const [candidates, others] = useMemo(() => {
    const fs = analysis?.findings ?? [];
    return [fs.filter((f) => f.top_candidate), fs.filter((f) => !f.top_candidate)];
  }, [analysis]);

  const name = (id: string) => bundle?.people.find((p) => p.id === id)?.display_name ?? id;

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>SiloBreaker</h1>
          <p className="tagline">Detect knowledge risk → Capture missing context → Verify transfer</p>
        </div>
        <button className="ghost" onClick={reset} disabled={!!busy}>
          Reset demo
        </button>
      </header>

      {error !== null && (
        <div className="banner">
          <ErrorNotice error={error} onReload={() => window.location.reload()} />
        </div>
      )}
      {busy && (
        <p className="busy" role="status">
          {busy}…
        </p>
      )}

      <section className="panel setup" aria-labelledby="setup-title">
        <header className="panel-head">
          <div>
            <p className="eyebrow">Handoff</p>
            <h2 id="setup-title">{bundle ? bundle.project_key : "Loading evidence…"}</h2>
          </div>
          {bundle && (
            <dl className="inventory">
              {Object.entries(bundle.source_inventory).map(([k, v]) => (
                <div key={k} className={`inv inv-${v}`}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
              <div className="inv">
                <dt>records</dt>
                <dd>{bundle.item_count}</dd>
              </div>
            </dl>
          )}
        </header>
        {bundle && !handoff && (
          <div className="row gap wrap end">
            <label className="field">
              <span>Experienced engineer (transferring)</span>
              <select value={expert} onChange={(e) => setExpert(e.target.value)}>
                {bundle.people.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Successor</span>
              <select value={successor} onChange={(e) => setSuccessor(e.target.value)}>
                {bundle.people.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.display_name}
                  </option>
                ))}
              </select>
            </label>
            <button onClick={start} disabled={!!busy || expert === successor}>
              Start handoff and analyse
            </button>
          </div>
        )}
        {handoff && (
          <p>
            {name(handoff.expert_id)} → {name(handoff.successor_id)}
            <span className="muted"> · bundle {bundle?.content_hash.slice(7, 19)}</span>
          </p>
        )}
      </section>

      {analysis && (
        <main className="layout">
          <section className="panel detect" aria-labelledby="detect-title">
            <header className="panel-head">
              <div>
                <p className="eyebrow">Step 1 · Detect</p>
                <h2 id="detect-title">Candidate knowledge gaps</h2>
              </div>
              <label className="field inline">
                <span>Analyse for</span>
                <select value={selectedEngineer} onChange={(e) => reanalyze(e.target.value)} disabled={!!busy}>
                  {bundle?.people.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.display_name}
                    </option>
                  ))}
                </select>
              </label>
            </header>
            <p className="muted small">
              {analysis.model_id} · {analysis.prompt_version} · scoring {analysis.scoring_version}
              {analysis.reused_extraction_from && " · same extraction snapshot, actor-sensitive signals recomputed"}
              {analysis.rejected_areas.length > 0 &&
                ` · ${analysis.rejected_areas.length} proposal(s) dropped for invalid citations`}
            </p>
            <p className="note">
              Review priority is a heuristic for what to ask first. It is not a probability of knowledge loss and not a
              judgement of any engineer.
            </p>
            {candidates.length === 0 && <p className="notice">No area qualifies as a ranked candidate for this engineer.</p>}
            {candidates.map((f) => (
              <FindingCard
                key={f.id}
                finding={f}
                selected={focus === f.id}
                onSelect={
                  selectedEngineer === handoff?.expert_id
                    ? () => {
                        setVerifyTarget(null);
                        setFocus(f.id);
                      }
                    : undefined
                }
                onEvidence={() => setEvidence(f.evidence_refs)}
              />
            ))}
            <details className="controls">
              <summary>Other areas examined ({others.length})</summary>
              {others.map((f) => (
                <FindingCard key={f.id} finding={f} selected={false} onEvidence={() => setEvidence(f.evidence_refs)} />
              ))}
            </details>
          </section>

          <div className="side">
            {focus ? (
              <CapturePanel
                key={focus}
                findingId={focus}
                onChanged={refreshAnalysis}
                onVerifyTarget={setVerifyTarget}
              />
            ) : (
              <section className="panel empty">
                <p className="eyebrow">Step 2 · Capture</p>
                <p>Choose a candidate and review it with the experienced engineer.</p>
              </section>
            )}
            {focus && verifyTarget && handoff ? (
              <VerifyPanel
                key={verifyTarget.id}
                versionId={verifyTarget.id}
                versionNo={verifyTarget.version_no}
                expertId={handoff.expert_id}
                successorId={handoff.successor_id}
              />
            ) : (
              <section className="panel empty">
                <p className="eyebrow">Step 3 · Verify</p>
                <p className="muted">Approve a Knowledge Unit first; exercises can only use approved knowledge.</p>
              </section>
            )}
          </div>
        </main>
      )}

      {evidence && <EvidenceDrawer refs={evidence} onClose={() => setEvidence(null)} />}
    </div>
  );
}
