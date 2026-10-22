import { useState, type FormEvent } from "react";
import { api, type UserPatch } from "../../api";
import { useAuth } from "../../auth";
import ErrorNotice from "../../components/ErrorNotice";
import Pager from "../../components/Pager";
import { useLoad } from "../../hooks";
import type { AdminUser, Role } from "../../types";

const SIZE = 10;

export default function UsersPage() {
  const { user: me } = useAuth();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [role, setRole] = useState<"" | Role>("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<AdminUser | "new" | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const { data, error, loading, reload } = useLoad(() => api.users({ q, role, page, size: SIZE }), [q, role, page]);

  const toggleActive = async (u: AdminUser) => {
    const verb = u.is_active ? "Deactivate" : "Reactivate";
    const consequence = u.is_active ? " They will be signed out everywhere and cannot sign in." : "";
    if (!window.confirm(`${verb} ${u.username}?${consequence}`)) return;
    setActionError(null);
    try {
      await api.updateUser(u.id, { is_active: !u.is_active });
      await reload();
    } catch (e) {
      setActionError(e);
    }
  };

  return (
    <section className="stack" aria-labelledby="users-title">
      <div className="row between wrap gap-s">
        <h2 id="users-title">Users</h2>
        <button onClick={() => setEditing("new")}>Add user</button>
      </div>

      <form
        className="panel filters"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setQ(search.trim());
        }}
      >
        <label className="field">
          <span>Search name or username</span>
          <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
        <label className="field">
          <span>Role</span>
          <select
            value={role}
            onChange={(e) => {
              setPage(1);
              setRole(e.target.value as "" | Role);
            }}
          >
            <option value="">All roles</option>
            <option value="admin">Administrator</option>
            <option value="member">Member</option>
          </select>
        </label>
        <div className="row end">
          <button type="submit">Search</button>
        </div>
      </form>

      {editing && (
        <UserForm
          user={editing === "new" ? null : editing}
          isSelf={editing !== "new" && editing.id === me?.id}
          onCancel={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await reload();
          }}
        />
      )}

      <ErrorNotice error={error ?? actionError} onReload={reload} />
      <div className="panel">
        {loading && <p role="status">Loading…</p>}
        {data && data.items.length === 0 && <p className="muted">No users match.</p>}
        {data && data.items.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">Username</th>
                  <th scope="col">Name</th>
                  <th scope="col">Role</th>
                  <th scope="col">Person</th>
                  <th scope="col">Status</th>
                  <th scope="col">Last sign-in</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((u) => (
                  <tr key={u.id} className={u.is_active ? "" : "inactive"}>
                    <td className="mono">{u.username}</td>
                    <td>{u.display_name ?? "—"}</td>
                    <td>{u.role === "admin" ? "Administrator" : "Member"}</td>
                    <td className="mono">{u.person_id ?? "—"}</td>
                    <td>{u.is_active ? "Active" : "Deactivated"}</td>
                    <td className="small nowrap">
                      {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "never"}
                    </td>
                    <td>
                      <div className="row gap-s">
                        <button className="ghost small" onClick={() => setEditing(u)} aria-label={`Edit ${u.username}`}>
                          Edit
                        </button>
                        {u.id !== me?.id && (
                          <button
                            className={u.is_active ? "danger small" : "secondary small"}
                            onClick={() => toggleActive(u)}
                            aria-label={`${u.is_active ? "Deactivate" : "Reactivate"} ${u.username}`}
                          >
                            {u.is_active ? "Deactivate" : "Reactivate"}
                          </button>
                        )}
                      </div>
                    </td>
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

function UserForm({
  user,
  isSelf,
  onCancel,
  onSaved,
}: {
  user: AdminUser | null;
  isSelf: boolean;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [role, setRole] = useState<Role>(user?.role ?? "member");
  const [personId, setPersonId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (user) {
        const patch: UserPatch = {};
        if (displayName !== (user.display_name ?? "")) patch.display_name = displayName || null;
        if (role !== user.role) patch.role = role;
        if (password) patch.password = password;
        await api.updateUser(user.id, patch);
      } else {
        await api.createUser({
          username: username.trim(),
          display_name: displayName.trim() || undefined,
          role,
          password,
          person_id: role === "member" && personId.trim() ? personId.trim() : undefined,
        });
      }
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const title = user ? `Edit ${user.username}` : "Add user";
  return (
    <form className="panel stack" onSubmit={submit} aria-label={title}>
      <h3>{title}</h3>
      <div className="form-grid">
        {!user && (
          <label className="field">
            <span>Username</span>
            <input value={username} onChange={(e) => setUsername(e.target.value)} required autoComplete="off" />
          </label>
        )}
        <label className="field">
          <span>Display name</span>
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </label>
        <label className="field">
          <span>Role</span>
          <select value={role} onChange={(e) => setRole(e.target.value as Role)} disabled={isSelf}>
            <option value="member">Member</option>
            <option value="admin">Administrator</option>
          </select>
        </label>
        {!user && role === "member" && (
          <label className="field">
            <span>Person ID in the evidence (defaults to the username)</span>
            <input value={personId} onChange={(e) => setPersonId(e.target.value)} placeholder={username || "username"} />
          </label>
        )}
        <label className="field">
          <span>{user ? "New password (leave empty to keep; signs the user out)" : "Password (at least 8 characters)"}</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required={!user}
            minLength={8}
            autoComplete="new-password"
          />
        </label>
      </div>
      {isSelf && <p className="muted small">You cannot change your own role or deactivate yourself.</p>}
      <ErrorNotice error={error} />
      <div className="row gap-s">
        <button type="submit" disabled={busy}>
          {user ? "Save changes" : "Create user"}
        </button>
        <button type="button" className="ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
