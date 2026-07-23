import { useEffect, useState } from "react";
import { api } from "./api.js";

export default function ResultsView({ jobId, onBack }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.jobResults(jobId).then(setData).catch((e) => setError(e.message));
  }, [jobId]);

  if (error)
    return (
      <div className="card">
        <div className="error-banner">{error}</div>
        <button className="ghost" onClick={onBack}>
          ← Back
        </button>
      </div>
    );
  if (!data) return <div className="card">Loading results…</div>;

  const { summary, metadata } = data;
  // Multi-construct runs summarize per construct + a correlation matrix;
  // single-construct summaries keep the original flat shape.
  const multi = Array.isArray(summary.constructs);

  return (
    <>
      <div className="results-toolbar">
        <button className="ghost" onClick={onBack}>
          ← Back to workspace
        </button>
        <div className="row result-actions">
          <a href={api.exportUrl(jobId)}>
            <button className="primary">Export results CSV</button>
          </a>
          <a href={api.scriptUrl(jobId)}>
            <button className="ghost">Python script</button>
          </a>
          <a href={api.scriptRequirementsUrl(jobId)}>
            <button className="ghost">requirements.txt</button>
          </a>
          <a href={api.metadataUrl(jobId)}>
            <button className="ghost">Run metadata (JSON)</button>
          </a>
        </div>
      </div>

      <div className="card">
        <h3>
          {metadata.construct} × {metadata.corpus_file}
        </h3>
        <p className="hint">
          CCR score = mean cosine similarity between each text and a construct&apos;s
          scale items. Higher = the text expresses the construct more strongly.
          {multi &&
            " All constructs were scored on the same pass over the corpus, so scores are row-aligned and directly comparable."}
        </p>

        <div className="stat-grid">
          <Stat k="Texts scored" v={summary.n_docs.toLocaleString()} />
          {multi ? (
            <Stat k="Constructs" v={summary.constructs.length} />
          ) : (
            <>
              <Stat k="Mean score" v={summary.score_mean.toFixed(3)} />
              <Stat k="SD" v={summary.score_sd.toFixed(3)} />
              <Stat k="Min" v={summary.score_min.toFixed(3)} />
              <Stat k="Max" v={summary.score_max.toFixed(3)} />
            </>
          )}
          {summary.n_dropped_empty > 0 && (
            <Stat k="Empty rows dropped" v={summary.n_dropped_empty} />
          )}
        </div>

        {summary.warnings?.length > 0 && (
          <div className="warnings mt">
            <strong className="small">Data-quality notes</strong>
            <ul className="small" style={{ margin: "4px 0 0", paddingLeft: 20 }}>
              {summary.warnings.map((w, i) => (
                <li key={i}>
                  {typeof w === "string" ? w : (
                    <>
                      <code style={{ fontSize: 11 }}>{w.code}</code> - {w.message}
                    </>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {multi && <CorrelationCard correlations={summary.correlations} />}

      {multi ? (
        summary.constructs.map((c, i) => (
          <details
            className="card construct-results"
            key={c.construct_id || i}
            open={summary.constructs.length <= 2}
          >
            <summary>
              <strong>{c.construct_name}</strong>
              <span className="picker-meta">
                {" "}
                mean {c.score_mean.toFixed(3)} · SD {c.score_sd.toFixed(3)} ·{" "}
                {c.n_items} item{c.n_items === 1 ? "" : "s"} · CSV columns{" "}
                <code>{c.column_prefix}_*</code>
              </span>
            </summary>
            <div className="stat-grid mt">
              <Stat k="Mean score" v={c.score_mean.toFixed(3)} />
              <Stat k="SD" v={c.score_sd.toFixed(3)} />
              <Stat k="Min" v={c.score_min.toFixed(3)} />
              <Stat k="Max" v={c.score_max.toFixed(3)} />
            </div>
            <h4>Score distribution</h4>
            <Histogram histogram={c.histogram} />
            <h4>Per-item mean loadings</h4>
            <ItemBars itemMeans={c.item_means} />
            <div className="row">
              <div className="grow">
                <h4>Highest-scoring texts</h4>
                <DocTable docs={c.top_docs} />
              </div>
              <div className="grow">
                <h4>Lowest-scoring texts</h4>
                <DocTable docs={c.bottom_docs} />
              </div>
            </div>
          </details>
        ))
      ) : (
        <>
          <div className="card">
            <h3>Score distribution</h3>
            <Histogram histogram={summary.histogram} />
          </div>

          <div className="card">
            <h3>Per-item mean loadings</h3>
            <p className="hint">
              Mean similarity of the corpus to each scale item - a face-validity check on which
              items drive the construct signal.
            </p>
            <ItemBars itemMeans={summary.item_means} />
          </div>

          <div className="row">
            <div className="grow card">
              <h3>Highest-scoring texts</h3>
              <DocTable docs={summary.top_docs} />
            </div>
            <div className="grow card">
              <h3>Lowest-scoring texts</h3>
              <DocTable docs={summary.bottom_docs} />
            </div>
          </div>
        </>
      )}

      <div className="meta-footer">
        <strong>Reproducibility record</strong> - model: <code>{metadata.model}</code> (dim{" "}
        {metadata.embedding_dim})
        {!multi && (
          <>
            {" "}· items hash: <code>{metadata.items_sha256_16}</code>
          </>
        )}{" "}
        · text column: <code>{metadata.text_column}</code> · run:{" "}
        {metadata.started_at} → {metadata.finished_at} ({metadata.duration_seconds}s) ·
        numpy {metadata.numpy}
        {metadata.sentence_transformers &&
          ` · sentence-transformers ${metadata.sentence_transformers}`}
        {multi ? (
          <div className="mt small">
            {metadata.constructs.map((c) => (
              <div key={c.column_prefix}>
                {c.name} — items hash <code>{c.items_sha256_16}</code>
                {c.reference ? ` · ${c.reference}` : ""}
              </div>
            ))}
          </div>
        ) : (
          <div className="mt small">
            Construct reference: {metadata.construct_reference || "-"}
          </div>
        )}
      </div>
    </>
  );
}

// Correlation table in the layout psychology papers use: rows "1. Name",
// columns numbered. Cell shading encodes sign (accent = positive, blue =
// negative) and strength (|r|).
function CorrelationCard({ correlations }) {
  const { constructs: names, matrix, n_texts } = correlations;

  function cellStyle(r, isDiag) {
    if (isDiag || r == null) return { color: "#98a2b3" };
    const alpha = Math.min(0.85, Math.abs(r));
    return {
      background: r >= 0 ? `rgba(122, 31, 61, ${alpha})` : `rgba(31, 77, 122, ${alpha})`,
      color: Math.abs(r) > 0.5 ? "#fff" : undefined,
      textAlign: "center",
    };
  }

  return (
    <div className="card">
      <h3>Construct interrelations</h3>
      <p className="hint">
        Pearson correlation between per-text CCR scores ({n_texts.toLocaleString()} texts).
        Positive r = the constructs rise and fall together in your corpus; negative r =
        texts high on one tend to be low on the other. The exported CSV contains every
        per-text score, so these are fully recomputable.
      </p>
      <div className="table-wrap">
        <table className="docs">
          <thead>
            <tr>
              <th />
              {names.map((n, i) => (
                <th key={i} style={{ textAlign: "center" }} title={n}>
                  {i + 1}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {names.map((rowName, i) => (
              <tr key={i}>
                <th style={{ textAlign: "left", fontWeight: 500 }}>
                  {i + 1}. {rowName}
                </th>
                {matrix[i].map((r, j) => (
                  <td key={j} style={cellStyle(r, i === j)}>
                    {i === j ? "—" : r == null ? "n/a" : r.toFixed(2)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ k, v }) {
  return (
    <div className="stat">
      <div className="v">{v}</div>
      <div className="k">{k}</div>
    </div>
  );
}

function ItemBars({ itemMeans }) {
  const maxItemMean = Math.max(...itemMeans.map((m) => Math.abs(m.mean)), 1e-9);
  return (
    <>
      {itemMeans.map((m, i) => (
        <div className="item-bar-row" key={i}>
          <span className="item-bar-label" title={m.item}>
            {m.item.length > 80 ? m.item.slice(0, 80) + "…" : m.item}
          </span>
          <div className="item-bar-track">
            <div
              className="item-bar-fill"
              style={{ width: `${Math.max(2, (Math.abs(m.mean) / maxItemMean) * 100)}%` }}
            />
          </div>
          <span className="item-bar-val">{m.mean.toFixed(3)}</span>
        </div>
      ))}
    </>
  );
}

function DocTable({ docs }) {
  return (
    <div className="table-wrap">
      <table className="docs">
        <thead>
          <tr>
            <th style={{ width: 60 }}>Score</th>
            <th>Text</th>
          </tr>
        </thead>
        <tbody>
          {docs.map((d) => (
            <tr key={d.row}>
              <td className="score">{d.score.toFixed(3)}</td>
              <td>{d.text}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Histogram({ histogram }) {
  const { counts, edges } = histogram;
  const W = 640;
  const H = 180;
  const PAD = { top: 10, right: 10, bottom: 26, left: 34 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const maxCount = Math.max(...counts, 1);
  const barW = plotW / counts.length;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", maxWidth: 720 }}>
      {/* y gridlines */}
      {[0.25, 0.5, 0.75, 1].map((f) => {
        const y = PAD.top + plotH - f * plotH;
        return (
          <g key={f}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y} y2={y} stroke="#eceef1" />
            <text x={PAD.left - 6} y={y + 4} fontSize="10" fill="#98a2b3" textAnchor="end">
              {Math.round(f * maxCount)}
            </text>
          </g>
        );
      })}
      {/* bars */}
      {counts.map((c, i) => {
        const h = (c / maxCount) * plotH;
        return (
          <rect
            key={i}
            x={PAD.left + i * barW + 1.5}
            y={PAD.top + plotH - h}
            width={Math.max(1, barW - 3)}
            height={h}
            rx="2"
            fill="#7a1f3d"
            opacity="0.85"
          >
            <title>
              {edges[i].toFixed(3)} – {edges[i + 1].toFixed(3)}: {c}
            </title>
          </rect>
        );
      })}
      {/* x labels: first, middle, last edges */}
      {[0, Math.floor(counts.length / 2), counts.length].map((i) => (
        <text
          key={i}
          x={PAD.left + i * barW}
          y={H - 8}
          fontSize="10"
          fill="#98a2b3"
          textAnchor="middle"
        >
          {edges[i].toFixed(2)}
        </text>
      ))}
      <line
        x1={PAD.left}
        x2={W - PAD.right}
        y1={PAD.top + plotH}
        y2={PAD.top + plotH}
        stroke="#d0d5dd"
      />
    </svg>
  );
}
