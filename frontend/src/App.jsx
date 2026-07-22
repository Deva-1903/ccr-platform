import { useEffect, useState } from "react";
import { api } from "./api.js";
import AdminPage from "./AdminPage.jsx";
import WelcomePage from "./WelcomePage.jsx";
import Workspace from "./Workspace.jsx";

const IS_ADMIN_PATH = window.location.pathname === "/admin";
// First visit lands on the welcome page; after "Open the dashboard" (or any
// return visit) the root goes straight to work. /welcome always shows it.
const WELCOME_SEEN_KEY = "ccr_welcome_seen";
const IS_WELCOME_PATH = window.location.pathname === "/welcome";

function relativeTime(iso) {
  if (!iso) return "";
  const then = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  const mins = Math.max(0, Math.floor((Date.now() - then.getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return then.toISOString().slice(0, 10);
}

function groupProjects(projects) {
  // Buckets by last activity: Today / This week / Earlier, with archived
  // projects collapsed into their own group at the bottom. Projects arrive
  // sorted by last activity (backend), so group order falls out naturally.
  const now = Date.now();
  const DAY = 86400000;
  const groups = { Today: [], "This week": [], Earlier: [], Archived: [] };
  for (const p of projects) {
    if (p.archived) {
      groups.Archived.push(p);
      continue;
    }
    const iso = p.last_activity_at || p.created_at;
    const t = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").getTime();
    const age = now - t;
    if (age < DAY) groups.Today.push(p);
    else if (age < 7 * DAY) groups["This week"].push(p);
    else groups.Earlier.push(p);
  }
  return Object.entries(groups).filter(([, items]) => items.length > 0);
}

export default function App() {
  const [projects, setProjects] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const [auth, setAuth] = useState(null);
  const [showLogin, setShowLogin] = useState(false);
  const [authMode, setAuthMode] = useState("signin"); // signin | register
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authName, setAuthName] = useState("");
  const [authError, setAuthError] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [inviteToken, setInviteToken] = useState("");
  const [showWelcome, setShowWelcome] = useState(
    IS_WELCOME_PATH ||
      (!IS_ADMIN_PATH && !localStorage.getItem(WELCOME_SEEN_KEY))
  );

  function enterDashboard() {
    localStorage.setItem(WELCOME_SEEN_KEY, "1");
    if (window.location.pathname !== "/") {
      window.history.replaceState({}, "", "/");
    }
    setShowWelcome(false);
  }

  // Invite links carry their role in the signed payload; decode it for the
  // banner only - the server re-verifies the signature on registration.
  const inviteRole = (() => {
    if (!inviteToken) return null;
    try {
      const data = JSON.parse(atob(inviteToken.split(".")[0].replace(/-/g, "+").replace(/_/g, "/")));
      return { lab: "lab member", external: "external user" }[data.invite] || null;
    } catch {
      return null;
    }
  })();

  const loadProjects = () =>
    api.listProjects().then(setProjects).catch((e) => setError(e.message));
  const loadAuth = () => api.authMe().then(setAuth).catch(() => {});

  useEffect(() => {
    loadProjects();
    loadAuth();
    // Surface Google sign-in failures passed back via redirect.
    const params = new URLSearchParams(window.location.search);
    const authFail = params.get("auth_error");
    if (authFail) {
      setError(`Sign-in problem: ${authFail.replaceAll("-", " ")}.`);
      window.history.replaceState({}, "", "/");
    }
    // Invite link (?invite=TOKEN): open the signup form with the token
    // attached. The URL keeps the token until signup succeeds, so a page
    // refresh doesn't lose the invite.
    const invite = params.get("invite");
    if (invite) {
      setInviteToken(invite);
      setAuthMode("register");
      setShowLogin(true);
      setShowWelcome(false); // invited people go straight to the signup form
    }
  }, []);

  async function handleAuthSubmit(e) {
    e.preventDefault();
    setAuthError("");
    setAuthBusy(true);
    try {
      if (authMode === "register") {
        await api.register({
          email: authEmail.trim(), password: authPassword, name: authName.trim(),
          ...(inviteToken ? { invite_token: inviteToken } : {}),
        });
        if (inviteToken) {
          setInviteToken("");
          window.history.replaceState({}, "", "/"); // invite consumed
        }
      } else {
        await api.login({ email: authEmail.trim(), password: authPassword });
      }
      setShowLogin(false);
      setAuthEmail("");
      setAuthPassword("");
      setAuthName("");
      await Promise.all([loadAuth(), loadProjects()]); // owned projects appear on sign-in
    } catch (err) {
      setAuthError(err.message);
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleLogout() {
    try {
      await api.logout();
      await Promise.all([loadAuth(), loadProjects()]);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    if (projects.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !projects.some((p) => p.id === selectedId)) {
      setSelectedId(projects[0].id);
    }
  }, [projects, selectedId]);

  async function createProject(e) {
    e.preventDefault();
    if (!newName.trim()) return;
    try {
      const p = await api.createProject({ name: newName.trim() });
      setNewName("");
      setCreating(false);
      await loadProjects();
      setSelectedId(p.id);
    } catch (err) {
      setError(err.message);
    }
  }

  const selected = projects.find((p) => p.id === selectedId) || null;
  const normalizedFilter = filter.trim().toLowerCase();
  const visibleProjects = projects.filter((p) =>
    p.name.toLowerCase().includes(normalizedFilter)
  );

  return (
    <div className="app">
      <header className="header">
        <a
          className="brand"
          href="/"
          onClick={(e) => {
            // Inside the SPA the brand is an instant way back to the
            // dashboard; from /admin it's a normal navigation.
            if (!IS_ADMIN_PATH) {
              e.preventDefault();
              enterDashboard();
            }
          }}
        >
          CCR Platform
        </a>
        <span className="sub">
          Contextualized Construct Representations · theory-driven psychological text analysis
        </span>
        <nav className="header-nav">
          {IS_ADMIN_PATH ? (
            <a className="header-link" href="/welcome">About</a>
          ) : (
            <button
              className={"header-link" + (showWelcome ? " current" : "")}
              onClick={() => setShowWelcome(true)}
            >
              About
            </button>
          )}
          <a className="header-link" href="/guide">Guide</a>
          <a className="header-link" href="/product">How it works</a>
          {auth?.signed_in ? (
            <>
              <span className="small">Hi, {auth.name}</span>
              {auth.is_admin && !IS_ADMIN_PATH && (
                <a className="header-btn" href="/admin">Admin</a>
              )}
              <button className="header-btn" onClick={handleLogout}>
                Sign out
              </button>
            </>
          ) : (
            <button className="header-btn" onClick={() => setShowLogin(true)}>
              Sign in
            </button>
          )}
        </nav>
      </header>

      {showLogin && (
        <div className="modal-backdrop" onClick={() => setShowLogin(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{authMode === "register" ? "Create an account" : "Sign in"}</h3>
            {inviteToken && authMode === "register" && (
              <p className="hint" style={{ fontWeight: 600 }}>
                🎟 You've been invited{inviteRole ? ` as a ${inviteRole}` : ""} - create
                your account below and the access comes with it.
              </p>
            )}
            <p className="hint">
              Accounts are free. Signing in lifts the anonymous limits
              {auth?.limits?.max_rows
                ? ` (${Math.round(auth.limits.max_bytes / 1048576)} MB / ${auth.limits.max_rows.toLocaleString()} rows per file, ${auth?.usage?.max_runs_per_day ?? 3} runs/day)`
                : ""}{" "}
              and keeps your datasets and runs instead of deleting them after analysis.
            </p>
            {authError && <p className="small" style={{ color: "var(--danger, #b3261e)" }}>{authError}</p>}
            {auth?.google_available && (
              <>
                <a className="primary google-btn" href="/api/auth/google/login">
                  Continue with Google
                </a>
                <p className="small muted" style={{ textAlign: "center", margin: "8px 0" }}>
                  or use email and password
                </p>
              </>
            )}
            <form onSubmit={handleAuthSubmit} className="mt">
              {authMode === "register" && (
                <label className="field">
                  Name
                  <input
                    type="text"
                    autoFocus
                    value={authName}
                    onChange={(e) => setAuthName(e.target.value)}
                    placeholder="e.g. Mohammad"
                  />
                </label>
              )}
              <label className="field">
                Email
                <input
                  type="email"
                  autoFocus={authMode === "signin"}
                  value={authEmail}
                  onChange={(e) => setAuthEmail(e.target.value)}
                  placeholder="you@example.com"
                />
              </label>
              <label className="field">
                Password
                {authMode === "register" && (
                  <span className="field-hint"> at least 8 characters</span>
                )}
                <input
                  type="password"
                  value={authPassword}
                  onChange={(e) => setAuthPassword(e.target.value)}
                />
              </label>
              <div className="row">
                <button
                  className="primary"
                  type="submit"
                  disabled={
                    authBusy ||
                    !authEmail.trim() ||
                    !authPassword ||
                    (authMode === "register" && !authName.trim())
                  }
                >
                  {authBusy ? "…" : authMode === "register" ? "Create account" : "Sign in"}
                </button>
                <button className="ghost" type="button" onClick={() => setShowLogin(false)}>
                  Cancel
                </button>
              </div>
            </form>
            <p className="small muted mt">
              {authMode === "register" ? (
                <>
                  Already have an account?{" "}
                  <button className="linkish" onClick={() => { setAuthMode("signin"); setAuthError(""); }}>
                    Sign in
                  </button>
                </>
              ) : (
                <>
                  New here?{" "}
                  <button className="linkish" onClick={() => { setAuthMode("register"); setAuthError(""); }}>
                    Create a free account
                  </button>
                </>
              )}
              {auth?.google_available
                ? " · Forgot your password? Contact the lab admin, or use Google."
                : " · Google sign-in arrives with lab accounts. Forgot your password? Contact the lab admin."}
            </p>
          </div>
        </div>
      )}

      {IS_ADMIN_PATH ? (
        <main className="main" style={{ maxWidth: 1100, margin: "0 auto", padding: "0 1rem" }}>
          <AdminPage auth={auth} />
        </main>
      ) : showWelcome ? (
        <main className="main" style={{ maxWidth: 920, margin: "0 auto", padding: "0 1rem" }}>
          <WelcomePage onEnter={enterDashboard} />
        </main>
      ) : (
      <div className="layout">
        <aside className="sidebar">
          <h2>
            Projects
            {projects.length > 0 && <span className="count">{projects.length}</span>}
          </h2>
          <input
            type="text"
            className="sidebar-filter"
            placeholder="Search projects..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <div className="project-list">
            {groupProjects(visibleProjects).map(([groupLabel, items]) => (
              <div key={groupLabel}>
                <div className="group-label">{groupLabel}</div>
                {items.map((p) => (
                  <button
                    key={p.id}
                    className={"project-item" + (p.id === selectedId ? " active" : "")}
                    onClick={() => setSelectedId(p.id)}
                    title={p.name}
                  >
                    <span className="project-name">{p.name}</span>
                    <span className="date">
                      {p.n_runs > 0 ? `${p.n_runs} run${p.n_runs === 1 ? "" : "s"} · ` : ""}
                      {relativeTime(p.last_activity_at || p.created_at)}
                    </span>
                  </button>
                ))}
              </div>
            ))}
            {filter && visibleProjects.length === 0 && (
              <p className="small muted">No projects match "{filter}".</p>
            )}
          </div>

          <div className="project-create">
            {creating ? (
              <form onSubmit={createProject}>
                <input
                  type="text"
                  autoFocus
                  placeholder="Project name"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                />
                <div className="row mt">
                  <button className="primary" type="submit">
                    Create
                  </button>
                  <button className="ghost" type="button" onClick={() => setCreating(false)}>
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <button className="ghost" onClick={() => setCreating(true)}>
                + New project
              </button>
            )}
          </div>
        </aside>

        <main className="main">
          {error && (
            <div className="error-banner" onClick={() => setError("")}>
              {error}
            </div>
          )}
          {selected ? (
            <Workspace
              key={selected.id}
              project={selected}
              auth={auth}
              onAuthRefresh={loadAuth}
              onProjectChanged={loadProjects}
              onProjectDeleted={() => {
                setSelectedId(null);
                loadProjects();
              }}
            />
          ) : (
            <div className="card empty-state">
              <h3>Create your first project</h3>
              <p className="hint">
                A project holds your datasets and runs. Upload a corpus (CSV/XLSX),
                choose a validated construct, and run a CCR analysis - results include
                per-item loadings, score distributions, and a reproducibility record
                for every run.
              </p>
              <div className="empty-actions">
                <button className="primary" onClick={() => setCreating(true)}>
                  + New project
                </button>
                <a className="ghost-link" href="/guide">Read the 5-minute guide</a>
              </div>
              <p className="small muted">
                Self-contained by design: embeddings run on this server itself - no
                third-party AI APIs. Please don&apos;t upload sensitive or identifiable
                data on this dev instance.
              </p>
            </div>
          )}
        </main>
      </div>
      )}
    </div>
  );
}
