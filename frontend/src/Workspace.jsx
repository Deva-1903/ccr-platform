import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import ConstructPicker from "./ConstructPicker.jsx";
import ResultsView from "./ResultsView.jsx";

export default function Workspace({ project, auth, onAuthRefresh, onProjectChanged, onProjectDeleted }) {
  const [corpora, setCorpora] = useState([]);
  const [constructs, setConstructs] = useState([]);
  const [models, setModels] = useState([]);
  const [jobs, setJobs] = useState([]);

  const [corpusId, setCorpusId] = useState("");
  const [textColumn, setTextColumn] = useState("");
  const [constructId, setConstructId] = useState("");
  const [modelName, setModelName] = useState("");
  const [languages, setLanguages] = useState(["en"]);
  const [language, setLanguage] = useState("en");
  const [uploading, setUploading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [showNewConstruct, setShowNewConstruct] = useState(false);
  const [viewJobId, setViewJobId] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteText, setDeleteText] = useState("");
  const fileRef = useRef(null);

  async function toggleArchive() {
    try {
      await api.patchProject(project.id, { archived: !project.archived });
      onProjectChanged?.();
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleDelete() {
    try {
      await api.deleteProject(project.id);
      setConfirmDelete(false);
      onProjectDeleted?.();
    } catch (err) {
      setError(err.message);
    }
  }

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
        const def = m.find((x) => x.default) || m[0];
        if (def) setModelName(def.id);
      })
      .catch((e) => setError(e.message));
    api.languages().then(setLanguages).catch(() => {});
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
        language,
      });
      await refreshJobs();
      onAuthRefresh?.(); // anonymous run counter changed
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

  const fileMissing = corpus && corpus.file_available === false;
  const canRun =
    corpusId && textColumn && constructId && modelName && !running && !fileMissing;

  return (
    <>
      {error && (
        <div className="error-banner" onClick={() => setError("")}>
          {error}
        </div>
      )}

      {/* Project header + actions */}
      <div className="project-header">
        <div>
          <span className="project-title">{project.name}</span>
          {project.archived && <span className="pill queued">archived</span>}
        </div>
        <div className="row">
          <button className="ghost" onClick={toggleArchive}>
            {project.archived ? "Unarchive" : "Archive"}
          </button>
          <button className="ghost danger" onClick={() => setConfirmDelete(true)}>
            Delete
          </button>
        </div>
      </div>

      {confirmDelete && (
        <div className="modal-backdrop" onClick={() => setConfirmDelete(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Delete "{project.name}"?</h3>
            <p className="hint">
              This permanently deletes {corpora.length} dataset{corpora.length === 1 ? "" : "s"},{" "}
              {jobs.length} run{jobs.length === 1 ? "" : "s"}, and all uploaded and result files.
              This cannot be undone. If you might need it later, use Archive instead.
            </p>
            <label className="field">
              Type the project name to confirm
              <input
                type="text"
                autoFocus
                value={deleteText}
                onChange={(e) => setDeleteText(e.target.value)}
                placeholder={project.name}
              />
            </label>
            <div className="row">
              <button
                className="primary danger-solid"
                disabled={deleteText !== project.name}
                onClick={handleDelete}
              >
                Delete permanently
              </button>
              <button
                className="ghost"
                onClick={() => {
                  setConfirmDelete(false);
                  setDeleteText("");
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Step 1 - corpus */}
      <div className="card">
        <h3>
          <span className="step-badge">1</span>Corpus
        </h3>
        <p className="hint">
          Upload a CSV or XLSX file, then choose the column containing the text to analyze.
          {auth && !auth.signed_in && auth.limits?.max_rows && (
            <>
              {" "}
              Anonymous limit: {Math.round(auth.limits.max_bytes / 1048576)} MB /{" "}
              {auth.limits.max_rows.toLocaleString()} rows per file; uploads are deleted
              after analysis. Sign in (top right) for larger uploads and to keep your data.
            </>
          )}
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
                <option value="">- select -</option>
                {corpora.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.filename} ({c.n_rows.toLocaleString()} rows)
                    {c.file_available === false ? " — re-upload to run" : ""}
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
                <option value="">- select -</option>
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
        {corpus && corpus.file_available === false && (
          <p className="small muted">
            ⚠ This dataset's file is no longer on the server (the instance restarted).
            Your past results for it are safe, but to run a new analysis, upload the
            file again above.
          </p>
        )}
      </div>

      {/* Step 2 - construct */}
      <div className="card">
        <h3>
          <span className="step-badge">2</span>Construct
        </h3>
        <p className="hint">
          Pick a validated scale from the library, or define custom items. CCR scores each
          text by its similarity to these items.
        </p>
        <div className="construct-row">
          <div className="grow">
            <ConstructPicker
              constructs={constructs}
              value={constructId}
              onChange={setConstructId}
            />
          </div>
          <button className="ghost" onClick={() => setShowNewConstruct((s) => !s)}>
            {showNewConstruct ? "Close" : "+ Custom construct"}
          </button>
        </div>

        {construct && (
          <>
            <ul className="construct-items">
              {construct.items.map((item, i) => (
                <li key={i}>
                  {item}
                  {construct.reverse_scored?.[i] ? " (reverse-scored)" : ""}
                </li>
              ))}
            </ul>
            {construct.reference && (
              <p className="small muted mt">Reference: {construct.reference}</p>
            )}
            {construct.verification_status !== "verified" && (
              <p className="small muted">
                ⚠ Item wording not yet verified verbatim against the original publication
                (status: {construct.verification_status.replace("_", " ")}).
              </p>
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

      {/* Step 3 - language, model + run */}
      <div className="card">
        <h3>
          <span className="step-badge">3</span>Language, model &amp; run
        </h3>
        <p className="hint">
          Embeddings run locally via sentence-transformers; model and language are recorded
          in the run metadata. If the corpus doesn&apos;t match the selected language or the
          model doesn&apos;t support it, you&apos;ll get a warning - never a silent result.
        </p>
        <div className="run-settings">
          <label className="field language-control">
            Text language
            <select value={language} onChange={(e) => setLanguage(e.target.value)}>
              {languages.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label className="field model-control">
            Embedding model
            <select value={modelName} onChange={(e) => setModelName(e.target.value)}>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <button className="primary run-button" disabled={!canRun} onClick={handleRun}>
            {running ? "Starting…" : "Run CCR analysis"}
          </button>
        </div>
        {auth && !auth.signed_in && auth.usage?.max_runs_per_day != null && (
          <p className="small muted">
            {Math.min(auth.usage.runs_used_today, auth.usage.max_runs_per_day)} of{" "}
            {auth.usage.max_runs_per_day} free runs used today
            {auth.usage.runs_used_today >= auth.usage.max_runs_per_day
              ? " - sign in (top right) to keep running."
              : "."}
          </p>
        )}
        {auth?.signed_in && auth.usage?.max_saved_runs != null && (
          <p className="small muted">
            {auth.usage.saved_runs} of {auth.usage.max_saved_runs} saved runs used.
          </p>
        )}
        {models.find((m) => m.id === modelName)?.warnings?.map((w, i) => (
          <p key={i} className="small muted">
            ⚠ {w}
          </p>
        ))}
      </div>

      {/* Jobs */}
      {jobs.length > 0 && (
        <div className="card">
          <h3>Runs</h3>
          <div className="table-wrap">
            <table className="docs">
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Corpus</th>
                  <th>Construct</th>
                  <th>Model</th>
                  <th>Lang</th>
                  <th style={{ width: "20%" }}>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id}>
                    <td className="muted">
                      {(j.started_at || j.created_at).replace("T", " ").slice(0, 16)}
                    </td>
                    <td>{j.corpus_filename}</td>
                    <td>{j.construct_name}</td>
                    <td className="muted small">{j.model_name}</td>
                    <td className="muted small">{j.language}</td>
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
        </div>
      )}
    </>
  );
}

const REVERSE_SUFFIX = /\s*\((r|rev|reversed)\)\s*$/i;

function NewConstructForm({ onCreated, onError }) {
  const [name, setName] = useState("");
  const [reference, setReference] = useState("");
  const [itemsText, setItemsText] = useState("");
  const [saving, setSaving] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [parseNotes, setParseNotes] = useState([]);
  const itemFileRef = useRef(null);

  // Convention shared with the file parser and the lab's own spreadsheets:
  // a trailing (R) marks a reverse-scored item.
  function parseLines() {
    return itemsText
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean)
      .map((line) => ({
        text: line.replace(REVERSE_SUFFIX, "").trim(),
        reverse: REVERSE_SUFFIX.test(line),
      }));
  }

  async function handleItemFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setParsing(true);
    setParseNotes([]);
    try {
      const parsed = await api.parseConstructFile(file);
      setItemsText(
        parsed.items
          .map((i) => (i.reverse_scored ? `${i.text} (R)` : i.text))
          .join("\n")
      );
      if (!name.trim() && parsed.suggested_name) setName(parsed.suggested_name);
      setParseNotes(parsed.warnings || []);
    } catch (err) {
      onError(err.message);
    } finally {
      setParsing(false);
      if (itemFileRef.current) itemFileRef.current.value = "";
    }
  }

  async function save(e) {
    e.preventDefault();
    const parsed = parseLines();
    if (!name.trim() || parsed.length === 0) {
      onError("A custom construct needs a name and at least one item (one per line).");
      return;
    }
    setSaving(true);
    try {
      const created = await api.createConstruct({
        name: name.trim(),
        reference,
        items: parsed.map((i) => i.text),
        reverse_scored: parsed.map((i) => i.reverse),
      });
      onCreated(created);
    } catch (err) {
      onError(err.message);
    } finally {
      setSaving(false);
    }
  }

  const nReverse = parseLines().filter((i) => i.reverse).length;

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
        Upload items from CSV/XLSX (optional) - an "item" column, or one item per row;
        reverse-scored via a "reverse" column or a trailing (R)
        <input
          ref={itemFileRef}
          type="file"
          accept=".csv,.xlsx,.xls"
          onChange={handleItemFile}
          disabled={parsing}
        />
      </label>
      {parsing && <p className="small muted">Parsing…</p>}
      {parseNotes.map((w, i) => (
        <p key={i} className="small muted">⚠ {w}</p>
      ))}
      <label className="field">
        Scale items - one per line, verbatim from the validated instrument; append (R) to
        mark a reverse-scored item
        <textarea rows={6} value={itemsText} onChange={(e) => setItemsText(e.target.value)} />
      </label>
      {nReverse > 0 && (
        <p className="small muted">{nReverse} item(s) marked reverse-scored.</p>
      )}
      <button className="primary" type="submit" disabled={saving || parsing}>
        {saving ? "Saving…" : "Save construct"}
      </button>
    </form>
  );
}
