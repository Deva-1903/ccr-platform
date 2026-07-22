import { useCallback, useEffect, useState } from "react";

// Minimal admin surface (v1): overview counters, user roles + password
// resets, failed-run requeue, and the RA's construct-verification queue.
// Access is enforced server-side (ADMIN_EMAILS allowlist or pi/maintainer
// role); this page just renders what the admin API returns. Actions a
// maintainer isn't allowed to take (granting staff roles, touching staff
// accounts) are rejected by the server and surface in the error banner.

const ROLES = ["external", "lab", "maintainer", "pi"];
const ROLE_LABELS = {
  external: "external user",
  lab: "lab member",
  maintainer: "maintainer",
  pi: "PI",
};

// Every admin card is collapsible; the big ones (verification queue, audit)
// start closed so the page stays scannable.
function Section({ title, hint, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="card">
      <h3
        onClick={() => setOpen((v) => !v)}
        style={{
          cursor: "pointer", userSelect: "none", display: "flex",
          justifyContent: "space-between", alignItems: "baseline", gap: ".6rem",
          marginBottom: open ? undefined : 0,
        }}
        title={open ? "Click to collapse" : "Click to expand"}
      >
        <span>{title}{!open && hint ? <span className="muted small" style={{ fontWeight: 400 }}> · {hint}</span> : null}</span>
        <span className="muted small" style={{ fontWeight: 400 }}>{open ? "▾" : "▸"}</span>
      </h3>
      {open && children}
    </div>
  );
}

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
  const [assignments, setAssignments] = useState([]);
  const [invites, setInvites] = useState([]);
  const [audit, setAudit] = useState(null); // null = not visible (maintainers)
  const [onlyUnverified, setOnlyUnverified] = useState(true);
  const [inviteRole, setInviteRole] = useState("lab");
  const [assignEmail, setAssignEmail] = useState("");
  const [assignRole, setAssignRole] = useState("lab");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // Only maintainers can flip verification statuses (the RA workflow);
  // PI/admin see the queue read-only. Enforced server-side too.
  const canVerify = auth?.role === "maintainer";

  const reload = useCallback(() => {
    setError("");
    adminFetch("/api/admin/overview").then(setOverview).catch((e) => setError(e.message));
    adminFetch("/api/admin/users").then(setUsers).catch(() => {});
    adminFetch("/api/admin/jobs/failed").then(setFailed).catch(() => {});
    adminFetch("/api/admin/role-assignments").then(setAssignments).catch(() => {});
    adminFetch("/api/admin/invites").then(setInvites).catch(() => {});
    adminFetch("/api/admin/audit").then(setAudit).catch(() => setAudit(null)); // 403 for maintainers
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

  async function copyInvite(inv) {
    const url = `${window.location.origin}/?invite=${encodeURIComponent(inv.token)}`;
    try {
      await navigator.clipboard.writeText(url);
      setNotice(`Invite link copied (${ROLE_LABELS[inv.role]}, expires ${inv.expires_at}). Paste it in Slack.`);
    } catch {
      setNotice(`Could not copy automatically - the link: ${url}`);
    }
  }

  return (
    <>
      {error && <div className="error-banner" onClick={() => setError("")}>{error}</div>}
      {notice && (
        <div className="card" style={{ borderColor: "var(--maroon)" }}>
          <p style={{ overflowWrap: "anywhere" }}><b>{notice}</b></p>
        </div>
      )}

      <div className="project-header">
        <span className="project-title">Admin</span>
        <a className="ghost header-btn" href="/">Back to platform</a>
      </div>

      {/* Overview */}
      <Section title="Overview">
        {overview ? (
          <p className="hint">
            <b>{overview.users}</b> accounts (
            {ROLES.filter((r) => overview.users_by_role?.[r])
              .map((r) => `${overview.users_by_role[r]} ${ROLE_LABELS[r]}`)
              .join(", ") || "none"}
            ; {overview.signups_last_7_days} new this week) · <b>{overview.runs_total}</b>{" "}
            runs total ({overview.runs_last_7_days} this week
            {overview.runs_by_status?.failed ? `, ${overview.runs_by_status.failed} failed` : ""}) ·{" "}
            <b>{overview.projects}</b> projects ({overview.anonymous_projects} anonymous) ·{" "}
            <b>{overview.constructs_unverified}</b> library scales awaiting verification
          </p>
        ) : (
          <p className="hint">Loading…</p>
        )}
      </Section>

      {/* Users */}
      <Section title="Users" hint={`${users.length} account${users.length === 1 ? "" : "s"}`}>
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
                  <td>
                    <select
                      value={u.role}
                      onChange={(e) =>
                        act(() => post(`/api/admin/users/${u.id}/role`, { role: e.target.value }))
                      }
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                      ))}
                    </select>
                  </td>
                  <td>{u.saved_runs}</td>
                  <td className="muted small">{u.google_only ? "Google" : "password"}</td>
                  <td>
                    {!u.google_only && (
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
                      </button>
                    )}{" "}
                    {!u.env_admin && (
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
      </Section>

      {/* Access before sign-in: pre-assigned roles + invite links */}
      <Section title="Access before sign-in">
        <p className="hint">
          <b>Pre-assign a role to an email</b> (e.g. an external collaborator who
          should land with full credentials): whoever first signs in with that
          email - password or Google - gets the role automatically.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!assignEmail.trim()) return;
            act(async () => {
              await post("/api/admin/role-assignments", {
                email: assignEmail.trim(), role: assignRole,
              });
              setAssignEmail("");
            });
          }}
          style={{ display: "flex", gap: ".5rem", flexWrap: "wrap", alignItems: "center" }}
        >
          <input
            type="email"
            placeholder="person@university.edu"
            value={assignEmail}
            onChange={(e) => setAssignEmail(e.target.value)}
            style={{ minWidth: "16rem" }}
          />
          <select value={assignRole} onChange={(e) => setAssignRole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>{ROLE_LABELS[r]}</option>
            ))}
          </select>
          <button type="submit" className="ghost" disabled={!assignEmail.trim()}>Pre-assign</button>
        </form>
        {assignments.length > 0 && (
          <div className="table-wrap">
            <table className="docs">
              <thead>
                <tr><th>Email</th><th>Role</th><th>By</th><th>Status</th><th /></tr>
              </thead>
              <tbody>
                {assignments.map((a) => (
                  <tr key={a.id}>
                    <td>{a.email}</td>
                    <td>{ROLE_LABELS[a.role] || a.role}</td>
                    <td className="muted small">{a.assigned_by}</td>
                    <td className="muted small">
                      {a.claimed_at ? `claimed ${a.claimed_at.slice(0, 10)}` : "pending"}
                    </td>
                    <td>
                      {!a.claimed_at && (
                        <button
                          className="linkish danger"
                          onClick={() =>
                            act(() => adminFetch(`/api/admin/role-assignments/${a.id}`, { method: "DELETE" }))
                          }
                        >
                          Remove
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="hint" style={{ marginTop: "1rem" }}>
          <b>Or create an invite link</b> (anyone with the link; lab member /
          external only - staff is granted per person above): paste it in Slack,
          it expires after a week. Revoking kills a link immediately; "used by"
          shows every account created through it.
        </p>
        <div style={{ display: "flex", gap: ".5rem", alignItems: "center" }}>
          <select value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}>
            <option value="lab">lab member</option>
            <option value="external">external user</option>
          </select>
          <button
            className="ghost"
            onClick={() =>
              act(async () => {
                const r = await post("/api/admin/invites", { role: inviteRole });
                await copyInvite(r);
              })
            }
          >
            Create invite link
          </button>
        </div>
        {invites.length > 0 && (
          <div className="table-wrap">
            <table className="docs">
              <thead>
                <tr><th>Role</th><th>Created</th><th>Expires</th><th>Status</th><th>Used by</th><th /></tr>
              </thead>
              <tbody>
                {invites.map((inv) => (
                  <tr key={inv.id}>
                    <td>{ROLE_LABELS[inv.role] || inv.role}</td>
                    <td className="muted small">{inv.created_at.slice(0, 10)} · {inv.created_by}</td>
                    <td className="muted small">{inv.expires_at}</td>
                    <td>
                      <span className={`pill ${inv.status === "active" ? "completed" : "queued"}`}>
                        {inv.status}
                      </span>
                    </td>
                    <td className="small">
                      {inv.redemptions.length === 0
                        ? <span className="muted">nobody yet</span>
                        : inv.redemptions.map((r) => (
                            <div key={r.email} title={r.at}>{r.email}</div>
                          ))}
                    </td>
                    <td>
                      {inv.status === "active" && (
                        <>
                          <button className="linkish" onClick={() => act(() => copyInvite(inv))}>
                            Copy link
                          </button>{" "}
                          <button
                            className="linkish danger"
                            onClick={() => {
                              if (window.confirm("Revoke this invite link? It stops working immediately.")) {
                                act(() => adminFetch(`/api/admin/invites/${inv.id}`, { method: "DELETE" }));
                              }
                            }}
                          >
                            Revoke
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* Audit trail - PI/env-admin only (404s/403s hide it for maintainers) */}
      {audit !== null && (
        <Section title="Audit trail" hint={`${audit.length} recent entries`} defaultOpen={false}>
          {audit.length === 0 ? (
            <p className="hint">No admin actions recorded yet.</p>
          ) : (
            <div className="table-wrap">
              <table className="docs">
                <thead>
                  <tr><th>When</th><th>Who</th><th>Action</th><th>Target</th><th>Detail</th></tr>
                </thead>
                <tbody>
                  {audit.map((a, i) => (
                    <tr key={i}>
                      <td className="muted small">{a.at.replace("T", " ").slice(0, 16)}</td>
                      <td className="small">{a.actor}</td>
                      <td className="small">{a.action.replaceAll("_", " ")}</td>
                      <td className="small">{a.target}</td>
                      <td className="muted small">{a.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {/* Failed runs */}
      <Section title="Failed runs" hint={failed.length ? `${failed.length} to triage` : "none"}>
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
      </Section>

      {/* Verification queue */}
      <Section
        title="Construct verification"
        hint={`${constructs.length} ${onlyUnverified ? "awaiting" : "listed"}`}
        defaultOpen={false}
      >
        <p className="hint">
          The maintainer's workflow: mark a scale verified once its wording is
          checked against the original publication (cross-reference the
          verification checklist spreadsheet). Statuses set here are applied
          back to the library files before production.
          {!canVerify && " Your account has read access; verification actions are for maintainers."}
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
                    {canVerify && (
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
                    )}
                  </td>
                </tr>
              ))}
              {constructs.length === 0 && (
                <tr><td colSpan={5} className="muted">Nothing awaiting verification. 🎉</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}
