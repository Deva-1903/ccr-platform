import { useCallback, useEffect, useState } from "react";

// Minimal admin surface (v1): overview counters, user roles + password
// resets, failed-run requeue, and the RA's construct-verification queue.
// Access is enforced server-side (ADMIN_EMAILS); this page just renders
// what the admin API returns.

async function adminFetch(path, options = {}) {
  const resp = await fetch(path, options);
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail || detail;
    } catch { /* non-JSON */ }
    throw new Error(detail);
  }
  return resp.status === 204 ? null : resp.json();
}

const post = (path, body) =>
  adminFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });

export default function AdminPage({ auth }) {
  const [overview, setOverview] = useState(null);
  const [users, setUsers] = useState([]);
  const [failed, setFailed] = useState([]);
  const [constructs, setConstructs] = useState([]);
  const [onlyUnverified, setOnlyUnverified] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const reload = useCallback(() => {
    setError("");
    adminFetch("/api/admin/overview").then(setOverview).catch((e) => setError(e.message));
    adminFetch("/api/admin/users").then(setUsers).catch(() => {});
    adminFetch("/api/admin/jobs/failed").then(setFailed).catch(() => {});
    adminFetch(
      "/api/admin/constructs" + (onlyUnverified ? "?status=needs_verification" : "")
    ).then(setConstructs).catch(() => {});
  }, [onlyUnverified]);

  useEffect(() => { reload(); }, [reload]);

  if (!auth?.signed_in || !auth?.is_admin) {
    return (
      <div className="card">
        <h3>Admin</h3>
        <p className="hint">
          This page requires an admin account.{" "}
          <a href="/">Back to the platform</a>.
        </p>
      </div>
    );
  }

  async function act(fn) {
    setError("");
    setNotice("");
    try {
      await fn();
      reload();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <>
      {error && <div className="error-banner" onClick={() => setError("")}>{error}</div>}
      {notice && (
        <div className="card" style={{ borderColor: "var(--maroon)" }}>
          <p><b>{notice}</b> (shown once - copy it now)</p>
        </div>
      )}

      <div className="project-header">
        <span className="project-title">Admin</span>
        <a className="ghost header-btn" href="/">Back to platform</a>
      </div>

      {/* Overview */}
      <div className="card">
        <h3>Overview</h3>
        {overview ? (
          <p className="hint">
            <b>{overview.users}</b> accounts ({overview.lab_users} lab tier,{" "}
            {overview.signups_last_7_days} new this week) · <b>{overview.runs_total}</b>{" "}
            runs total ({overview.runs_last_7_days} this week
            {overview.runs_by_status?.failed ? `, ${overview.runs_by_status.failed} failed` : ""}) ·{" "}
            <b>{overview.projects}</b> projects ({overview.anonymous_projects} anonymous) ·{" "}
            <b>{overview.constructs_unverified}</b> library scales awaiting verification
          </p>
        ) : (
          <p className="hint">Loading…</p>
        )}
      </div>

      {/* Users */}
      <div className="card">
        <h3>Users</h3>
        <div className="table-wrap">
          <table className="docs">
            <thead>
              <tr><th>Email</th><th>Name</th><th>Role</th><th>Saved runs</th><th>Sign-in</th><th /></tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.email}{u.is_admin ? " ★" : ""}</td>
                  <td>{u.name}</td>
                  <td><span className={`pill ${u.role === "lab" ? "completed" : "queued"}`}>{u.role}</span></td>
                  <td>{u.saved_runs}</td>
                  <td className="muted small">{u.google_only ? "Google" : "password"}</td>
                  <td>
                    <button
                      className="linkish"
                      onClick={() =>
                        act(() => post(`/api/admin/users/${u.id}/role`, {
                          role: u.role === "lab" ? "member" : "lab",
                        }))
                      }
                    >
                      {u.role === "lab" ? "Make member" : "Make lab (unlimited)"}
                    </button>{" "}
                    <button
                      className="linkish"
                      onClick={() =>
                        act(async () => {
                          const r = await post(`/api/admin/users/${u.id}/reset-password`);
                          setNotice(`Temporary password for ${r.email}: ${r.temporary_password}`);
                        })
                      }
                    >
                      Reset password
                    </button>{" "}
                    {!u.is_admin && (
                      <button
                        className="linkish danger"
                        onClick={() => {
                          if (window.confirm(`Delete ${u.email} and ALL their data?`)) {
                            act(() => adminFetch(`/api/admin/users/${u.id}`, { method: "DELETE" }));
                          }
                        }}
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr><td colSpan={6} className="muted">No accounts yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Failed runs */}
      <div className="card">
        <h3>Failed runs</h3>
        {failed.length === 0 ? (
          <p className="hint">None. 🎉</p>
        ) : (
          <div className="table-wrap">
            <table className="docs">
              <thead>
                <tr><th>When</th><th>Corpus</th><th>Model</th><th>Error</th><th /></tr>
              </thead>
              <tbody>
                {failed.map((j) => (
                  <tr key={j.id}>
                    <td className="muted">{j.created_at.replace("T", " ").slice(0, 16)}</td>
                    <td>{j.corpus_filename}</td>
                    <td className="muted small">{j.model_name}</td>
                    <td className="small" title={j.error_tail}>{j.error_tail.slice(0, 90)}</td>
                    <td>
                      {j.corpus_file_available ? (
                        <button
                          className="linkish"
                          onClick={() => act(() => post(`/api/admin/jobs/${j.id}/requeue`))}
                        >
                          Requeue
                        </button>
                      ) : (
                        <span className="muted small">file expired</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Verification queue */}
      <div className="card">
        <h3>Construct verification</h3>
        <p className="hint">
          For the RA workflow: mark a scale verified once its wording is checked
          against the original publication (cross-reference the verification
          checklist spreadsheet). Statuses set here are applied back to the
          library files before production.
          {" "}
          <button className="linkish" onClick={() => setOnlyUnverified((v) => !v)}>
            {onlyUnverified ? "Show all" : "Show unverified only"}
          </button>
        </p>
        <div className="table-wrap">
          <table className="docs">
            <thead>
              <tr><th>Scale</th><th>Category</th><th>Items</th><th>Status</th><th /></tr>
            </thead>
            <tbody>
              {constructs.map((c) => (
                <tr key={c.id}>
                  <td title={c.reference}>{c.name}</td>
                  <td className="muted small">{c.category}</td>
                  <td>{c.n_items}</td>
                  <td>
                    <span className={`pill ${c.verification_status === "verified" ? "completed" : "queued"}`}>
                      {c.verification_status.replace("_", " ")}
                    </span>
                  </td>
                  <td>
                    <button
                      className="linkish"
                      onClick={() =>
                        act(() => post(`/api/admin/constructs/${c.id}/verification`, {
                          status: c.verification_status === "verified"
                            ? "needs_verification"
                            : "verified",
                        }))
                      }
                    >
                      {c.verification_status === "verified" ? "Un-verify" : "Mark verified"}
                    </button>
                  </td>
                </tr>
              ))}
              {constructs.length === 0 && (
                <tr><td colSpan={5} className="muted">Nothing awaiting verification. 🎉</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
