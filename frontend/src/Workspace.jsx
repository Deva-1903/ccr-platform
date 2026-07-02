import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import ResultsView from "./ResultsView.jsx";

export default function Workspace({ project }) {
  const [corpora, setCorpora] = useState([]);
  const [constructs, setConstructs] = useState([]);
  const [models, setModels] = useState([]);
  const [jobs, setJobs] = useState([]);

  const [corpusId, setCorpusId] = useState("");
  const [textColumn, setTextColumn] = useState("");
  const [constructId, setConstructId] = useState("");
  const [modelName, setModelName] = useState("");
  const [uploading, setUploading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [showNewConstruct, setShowNewConstruct] = useState(false);
  const [viewJobId, setViewJobId] = useState(null);
  const fileRef = useRef(null);

  const refreshJobs = useCallback(
    () => api.listJobs(project.id).then(setJobs).catch(() => {}),
    [project.id]
  );

  useEffect(() => {
    api.listCorpora(project.id).then(setCorpora).catch((e) => setError(e.message));
    api.listConstructs().then(setConstructs).catch((e) => setError(e.message));
    api
      .models()
      .then((m) => {
        setModels(m);
        if (m.length) setModelName(m[0].name);
      })
      .catch((e) => setError(e.message));
    refreshJobs();
  }, [project.id, refreshJobs]);

  // Poll while any job is active.
  const anyActive = jobs.some((j) => j.status === "queued" || j.status === "running");
  useEffect(() => {
    if (!anyActive) return undefined;
    const t = setInterval(refreshJobs, 1200);
    return () => clearInterval(t);
  }, [anyActive, refreshJobs]);

  const corpus = corpora.find((c) => c.id === corpusId) || null;
  const construct = constructs.find((c) => c.id === constructId) || null;

  async function handleUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const uploaded = await api.uploadCorpus(project.id, file);
      const list = await api.listCorpora(project.id);
      setCorpora(list);
      setCorpusId(uploaded.id);
      setTextColumn(uploaded.suggested_text_column || uploaded.columns[0]);
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function handleRun() {
    setRunning(true);
    setError("");
    try {
      await api.createJob({
        project_id: project.id,
        corpus_id: corpusId,
        construct_id: constructId,
        text_column: textColumn,
        model_name: modelName,
      });
      await refreshJobs();
    } catch (err) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  }

  if (viewJobId) {
    return (
      <ResultsView
        jobId={viewJobId}
        onBack={() => {
          setViewJobId(null);
          refreshJobs();
        }}
      />
    );
  }

  const canRun = corpusId && textColumn && constructId && modelName && !running;

  return (
    <>
      {error && (
        <div className="error-banner" onClick={() => setError("")}>
          {error}
        </div>
      )}

      {/* Step 1 — corpus */}
      <div className="card">
        <h3>
          <span className="step-badge">1</span>Corpus
        </h3>
        <p className="hint">
          Upload a CSV or XLSX file, then choose the column containing the text to analyze.
        </p>
        <div className="row">
          <div className="grow">
            <label className="field">
              Upload file
              <input
                ref={fileRef}
                type="file"
                accept=".csv,.xlsx,.xls"
                onChange={handleUpload}
                disabled={uploading}
              />
            </label>
            {uploading && <span className="small muted">Uploading…</span>}
          </div>
          <div className="grow">
            <label className="field">
              Corpus
              <select value={corpusId} onChange={(e) => setCorpusId(e.target.value)}>
                <option value="">— select —</option>
                {corpora.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.filename} ({c.n_rows.toLocaleString()} rows)
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="grow">
            <label className="field">
              Text column
              <select
                value={textColumn}
                onChange={(e) => setTextColumn(e.target.value)}
                disabled={!corpus}
              >
                <option value="">— select —</option>
                {corpus?.columns.map((col) => (
                  <option key={col} value={col}>
                    {col}
                    {col === corpus.suggested_text_column ? " (suggested)" : ""}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
        {corpus?.parse_info?.note && (
          <p className="small muted">⚠ {corpus.parse_info.note}</p>
        )}
      </div>

      {/* Step 2 — construct */}
      <div className="card">
        <h3>
          <span className="step-badge">2</span>Construct
        </h3>
        <p className="hint">
          Pick a validated scale from the library, or define custom items. CCR scores each
          text by its similarity to these items.
        </p>
        <div className="row">
          <div className="grow">
            <select value={constructId} onChange={(e) => setConstructId(e.target.value)}>
              <option value="">— select construct —</option>
              {constructs.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.items.length} items{c.is_seed ? ", library" : ", custom"})
                </option>
              ))}
            </select>
          </div>
          <button className="ghost" onClick={() => setShowNewConstruct((s) => !s)}>
            {showNewConstruct ? "Close" : "+ Custom construct"}
          </button>
        </div>

        {construct && (
          <>
            <ul className="construct-items">
              {construct.items.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
            {construct.reference && (
              <p className="small muted mt">Reference: {construct.reference}</p>
            )}
          </>
        )}

        {showNewConstruct && (
          <NewConstructForm
            onCreated={async (created) => {
              const list = await api.listConstructs();
              setConstructs(list);
              setConstructId(created.id);
              setShowNewConstruct(false);
            }}
            onError={setError}
          />
        )}
      </div>

      {/* Step 3 — model + run */}
      <div className="card">
        <h3>
          <span className="step-badge">3</span>Model &amp; run
        </h3>
        <p className="hint">
          Embeddings run locally via sentence-transformers; the model is pinned and recorded
          in the run metadata for reproducibility.
        </p>
        <div className="row">
          <div className="grow">
            <select value={modelName} onChange={(e) => setModelName(e.target.value)}>
              {models.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>
          <button className="primary" disabled={!canRun} onClick={handleRun}>
            {running ? "Starting…" : "Run CCR analysis"}
          </button>
        </div>
      </div>

      {/* Jobs */}
      {jobs.length > 0 && (
        <div className="card">
          <h3>Runs</h3>
          <table className="docs">
            <thead>
              <tr>
                <th>Started</th>
                <th>Corpus</th>
                <th>Construct</th>
                <th style={{ width: "24%" }}>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td className="muted">{(j.started_at || j.created_at).replace("T", " ").slice(0, 16)}</td>
                  <td>{j.corpus_filename}</td>
                  <td>{j.construct_name}</td>
                  <td>
                    {j.status === "running" ? (
                      <div className="progress-track" title={`${Math.round(j.progress * 100)}%`}>
                        <div
                          className="progress-fill"
                          style={{ width: `${Math.max(3, j.progress * 100)}%` }}
                        />
                      </div>
                    ) : (
                      <span className={`pill ${j.status}`}>{j.status}</span>
                    )}
                    {j.status === "failed" && (
                      <div className="small muted" title={j.error}>
                        {j.error.split("\n").pop()}
                      </div>
                    )}
                  </td>
                  <td>
                    {j.status === "completed" && (
                      <button className="linkish" onClick={() => setViewJobId(j.id)}>
                        View results
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function NewConstructForm({ onCreated, onError }) {
  const [name, setName] = useState("");
  const [reference, setReference] = useState("");
  const [itemsText, setItemsText] = useState("");
  const [saving, setSaving] = useState(false);

  async function save(e) {
    e.preventDefault();
    const items = itemsText
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    if (!name.trim() || items.length === 0) {
      onError("A custom construct needs a name and at least one item (one per line).");
      return;
    }
    setSaving(true);
    try {
      const created = await api.createConstruct({ name: name.trim(), reference, items });
      onCreated(created);
    } catch (err) {
      onError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={save} className="mt">
      <div className="row">
        <div className="grow">
          <label className="field">
            Name
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
        </div>
        <div className="grow">
          <label className="field">
            Reference (publication, optional)
            <input
              type="text"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
            />
          </label>
        </div>
      </div>
      <label className="field">
        Scale items — one per line, verbatim from the validated instrument
        <textarea rows={5} value={itemsText} onChange={(e) => setItemsText(e.target.value)} />
      </label>
      <button className="primary" type="submit" disabled={saving}>
        {saving ? "Saving…" : "Save construct"}
      </button>
    </form>
  );
}
