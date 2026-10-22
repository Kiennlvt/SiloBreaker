import { useState, type FormEvent } from "react";
import { api } from "../../api";
import ErrorNotice from "../../components/ErrorNotice";
import Pager from "../../components/Pager";
import { useLoad } from "../../hooks";

const SIZE = 25;
type Filters = { actor: string; action: string; date_from: string; date_to: string };
const EMPTY: Filters = { actor: "", action: "", date_from: "", date_to: "" };

export default function AuditPage() {
  const [draft, setDraft] = useState<Filters>(EMPTY);
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useLoad(
    () => api.audit({ ...filters, page, size: SIZE }),
    [filters, page],
  );

  const apply = (e: FormEvent) => {
    e.preventDefault();
    setPage(1);
    setFilters(draft);
  };
  const set = (k: keyof Filters) => (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [k]: e.target.value }));

  return (
    <section className="stack" aria-labelledby="audit-title">
      <h2 id="audit-title">Audit log</h2>
      <form className="panel filters" onSubmit={apply}>
        <label className="field">
          <span>Actor</span>
          <input value={draft.actor} onChange={set("actor")} placeholder="e.g. alice" />
        </label>
        <label className="field">
          <span>Action</span>
          <input value={draft.action} onChange={set("action")} placeholder="e.g. auth.login" />
        </label>
        <label className="field">
          <span>From (UTC day)</span>
          <input type="date" value={draft.date_from} onChange={set("date_from")} />
        </label>
        <label className="field">
          <span>To (UTC day)</span>
          <input type="date" value={draft.date_to} onChange={set("date_to")} />
        </label>
        <div className="row gap-s end">
          <button type="submit">Apply filters</button>
          <button
            type="button"
            className="ghost"
            onClick={() => {
              setDraft(EMPTY);
              setFilters(EMPTY);
              setPage(1);
            }}
          >
            Clear
          </button>
        </div>
      </form>
      <ErrorNotice error={error} onReload={reload} />
      <div className="panel">
        {loading && <p role="status">Loading…</p>}
        {data && data.items.length === 0 && <p className="muted">No events match these filters.</p>}
        {data && data.items.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Actor</th>
                  <th scope="col">Action</th>
                  <th scope="col">Target</th>
                  <th scope="col">Details</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((e) => (
                  <tr key={e.id}>
                    <td className="nowrap small">{new Date(e.created_at).toLocaleString()}</td>
                    <td>{e.actor_id}</td>
                    <td className="mono">{e.action}</td>
                    <td className="small">
                      {e.target_type}
                      {e.target_revision !== null && ` rev ${e.target_revision}`}
                    </td>
                    <td className="mono small break">{JSON.stringify(e.metadata)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && <Pager page={data.page} size={data.size} total={data.total} onPage={setPage} />}
      </div>
    </section>
  );
}
