import { Link } from "react-router-dom";
import { api } from "../../api";
import ErrorNotice from "../../components/ErrorNotice";
import { useLoad } from "../../hooks";

export default function AdminOverview() {
  const { data, error, reload } = useLoad(
    async () => {
      const [users, members, handoffs, audit] = await Promise.all([
        api.users({ size: 1 }),
        api.users({ role: "member", size: 1 }),
        api.handoffs(),
        api.audit({ size: 5 }),
      ]);
      return { users: users.total, members: members.total, handoffs: handoffs.length, audit: audit.items };
    },
    [],
  );

  return (
    <section className="stack" aria-labelledby="overview-title">
      <h2 id="overview-title">Administration</h2>
      <ErrorNotice error={error} onReload={reload} />
      <div className="tiles">
        <Link className="tile" to="/admin/users">
          <span className="tile-num">{data?.users ?? "…"}</span>
          <span className="tile-label">accounts ({data?.members ?? "…"} members)</span>
        </Link>
        <Link className="tile" to="/admin/handoffs">
          <span className="tile-num">{data?.handoffs ?? "…"}</span>
          <span className="tile-label">handoffs</span>
        </Link>
        <Link className="tile" to="/library">
          <span className="tile-num">→</span>
          <span className="tile-label">approved knowledge</span>
        </Link>
      </div>
      <section className="panel" aria-labelledby="recent-title">
        <div className="row between wrap">
          <h3 id="recent-title">Recent activity</h3>
          <Link to="/admin/audit">Open audit log</Link>
        </div>
        {data && data.audit.length === 0 && <p className="muted">No activity yet.</p>}
        <ul className="plain-list">
          {data?.audit.map((e) => (
            <li key={e.id}>
              <span className="mono small">{new Date(e.created_at).toLocaleString()}</span> · <strong>{e.actor_id}</strong>{" "}
              {e.action}
            </li>
          ))}
        </ul>
      </section>
    </section>
  );
}
