// "Cite this platform" dialog, reached from the landing-page footer.
// Requested by Ali Hajian (2026-09-09), modelled on Google Scholar's Cite
// button: the same reference in five styles, click one to copy it, with
// BibTeX and RIS for reference managers underneath.
//
// Every string comes from GET /api/citation (backend/app/citation.py). The UI
// formats nothing itself, so the dialog, the repo's CITATION.cff and the
// version stamped into run metadata cannot drift apart.
import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

// Clipboard access needs a secure context. It is there on the deployment
// (HTTPS) and on localhost, but not on a plain-HTTP LAN address, which is how
// a lab machine sometimes reaches a dev instance - hence the fallback rather
// than a dead button.
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(area);
      return ok;
    } catch {
      return false;
    }
  }
}

export default function CiteDialog({ onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");  // id of the row just copied
  const [exportView, setExportView] = useState("");  // "" | "bibtex" | "ris"
  const dialogRef = useRef(null);

  useEffect(() => {
    api.citation().then(setData).catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    // Escape closes, and focus moves into the dialog so a keyboard user is
    // not left behind on the footer link.
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    dialogRef.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (!copied) return undefined;
    const t = setTimeout(() => setCopied(""), 1800);
    return () => clearTimeout(t);
  }, [copied]);

  async function copy(id, text, node) {
    const ok = await copyText(text);
    setCopied(ok ? id : "");
    if (ok) {
      setError("");
      return;
    }
    // No clipboard (an old browser, or a plain-HTTP address): select the
    // reference so the next keystroke copies it, rather than leaving the
    // click doing nothing.
    if (node) {
      const range = document.createRange();
      range.selectNodeContents(node);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    }
    setError("This browser blocked the clipboard. The citation is selected: press Ctrl+C or Cmd+C.");
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div
        className="modal modal-wide cite-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Cite this platform"
        tabIndex={-1}
        ref={dialogRef}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h3>Cite this platform</h3>
          <button className="linkish cite-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {error && <div className="error-banner">{error}</div>}
        {!data && !error && <p className="small muted">Loading…</p>}

        {data && (
          <>
            <p className="hint">
              Version {data.platform.version}. Click a citation to copy it.
            </p>

            <div className="cite-list">
              {data.styles.map((s) => (
                <button
                  type="button"
                  className="cite-row"
                  key={s.id}
                  onClick={(e) =>
                    copy(s.id, data.platform.styles[s.id], e.currentTarget.querySelector(".cite-text"))
                  }
                  title={`Copy the ${s.label} citation`}
                >
                  <span className="cite-style">{s.label}</span>
                  <span className="cite-text">{data.platform.styles[s.id]}</span>
                  <span className="cite-copied" aria-live="polite">
                    {copied === s.id ? "Copied" : ""}
                  </span>
                </button>
              ))}
            </div>

            <div className="cite-also">
              <b>Also cite the method.</b> Results produced here rest on the CCR
              papers, so a methods section needs them alongside the platform.
              The BibTeX and RIS below contain all three.
              <ul>
                {data.method.map((m) => (
                  <li key={m.key}>{m.apa}</li>
                ))}
              </ul>
            </div>

            <div className="cite-actions">
              <button
                className="ghost"
                onClick={() => setExportView(exportView === "bibtex" ? "" : "bibtex")}
              >
                BibTeX
              </button>
              <button
                className="ghost"
                onClick={() => setExportView(exportView === "ris" ? "" : "ris")}
              >
                RIS (EndNote, Zotero, Mendeley)
              </button>
            </div>

            {exportView && (
              <div className="cite-export">
                <pre>{data[exportView]}</pre>
                <button
                  className="ghost"
                  onClick={(e) =>
                    copy(exportView, data[exportView], e.currentTarget.parentElement.querySelector("pre"))
                  }
                >
                  {copied === exportView ? "Copied" : `Copy ${exportView === "ris" ? "RIS" : "BibTeX"}`}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
