import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api";
import CapturePanel, { type VerifyTarget } from "../../components/CapturePanel";
import ErrorNotice from "../../components/ErrorNotice";
import EvidenceDrawer from "../../components/EvidenceDrawer";
import FindingCard from "../../components/FindingCard";
import { useLoad } from "../../hooks";
import type { EvidenceRef } from "../../types";

export default function FindingPage() {
  const { id = "" } = useParams();
  const [evidence, setEvidence] = useState<EvidenceRef[] | null>(null);
  const [target, setTarget] = useState<VerifyTarget>(null);
  const { data, error, reload } = useLoad(() => api.finding(id), [id]);

  return (
    <div className="layout">
      <section className="stack">
        {data && (
          <Link className="small" to={`/expert/handoffs/${data.handoff.id}/detect`}>
            ← Back to all findings
          </Link>
        )}
        <ErrorNotice error={error} onReload={reload} />
        {data && <FindingCard finding={data} selected onEvidence={() => setEvidence(data.evidence_refs)} />}
      </section>
      <div className="side">
        <CapturePanel findingId={id} onChanged={reload} onVerifyTarget={setTarget} />
        <section className="panel">
          <p className="eyebrow">Step 3 · Verify</p>
          {target ? (
            <>
              <p>Knowledge v{target.version_no} is approved. Build an exercise to check the successor understood it.</p>
              <Link className="button" to={`/expert/knowledge/${target.id}/exercise`}>
                Open exercise for v{target.version_no}
              </Link>
            </>
          ) : (
            <p className="muted">Approve a Knowledge Unit first; exercises can only use approved knowledge.</p>
          )}
        </section>
      </div>
      {evidence && <EvidenceDrawer refs={evidence} onClose={() => setEvidence(null)} />}
    </div>
  );
}
