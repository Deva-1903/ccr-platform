import { useEffect, useState } from "react";
import { api } from "./api.js";
import Workspace from "./Workspace.jsx";

export default function App() {
  const [projects, setProjects] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [error, setError] = useState("");

  const loadProjects = () =>
    api.listProjects().then(setProjects).catch((e) => setError(e.message));

  useEffect(() => {
    loadProjects();
  }, []);

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

  return (
    <div className="app">
      <header className="header">
        <h1>CCR Platform</h1>
        <span className="sub">
          Contextualized Construct Representations · theory-driven psychological text analysis
        </span>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <h2>Projects</h2>
          {projects.map((p) => (
            <button
              key={p.id}
              className={"project-item" + (p.id === selectedId ? " active" : "")}
              onClick={() => setSelectedId(p.id)}
            >
              {p.name}
              <span className="date">{p.created_at.slice(0, 10)}</span>
            </button>
          ))}

          {creating ? (
            <form onSubmit={createProject} className="mt">
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
            <button className="ghost mt" onClick={() => setCreating(true)}>
              + New project
            </button>
          )}
        </aside>

        <main className="main">
          {error && (
            <div className="error-banner" onClick={() => setError("")}>
              {error}
            </div>
          )}
          {selected ? (
            <Workspace key={selected.id} project={selected} />
          ) : (
            <div className="card">
              <h3>Welcome</h3>
              <p className="hint">
                Create or select a project, upload a corpus (CSV/XLSX), choose a validated
                construct, and run a CCR analysis. Results include per-item loadings,
                score distributions, and a reproducibility record for every run.
              </p>
              <p className="small muted">
                Self-contained by design: embeddings run on this server itself — no
                third-party AI APIs. Demo instance: storage is ephemeral and may reset;
                please don&apos;t upload sensitive or identifiable data.
              </p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
