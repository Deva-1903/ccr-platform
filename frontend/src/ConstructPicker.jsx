import { useEffect, useMemo, useRef, useState } from "react";

// Searchable, grouped construct picker. A flat dropdown stops working past
// ~15 options; the library is at 99 and growing. Researchers either know the
// scale ("GAD-7") or the family ("empathy"), so search matches name, category,
// and questionnaire, results group by category, and the last 5 used constructs
// stay on top (researchers re-run the same scales constantly).
// Keyboard: ArrowUp/Down move, Enter selects, Escape closes.

const RECENT_KEY = "ccr_recent_constructs";
const RECENT_MAX = 5;

function readRecent() {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
  } catch {
    return [];
  }
}

export function rememberRecent(id) {
  const next = [id, ...readRecent().filter((x) => x !== id)].slice(0, RECENT_MAX);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable: recents simply don't persist */
  }
}

export default function ConstructPicker({ constructs, value, onChange }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const rootRef = useRef(null);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  const selected = constructs.find((c) => c.id === value) || null;

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const match = (c) =>
      !q ||
      c.name.toLowerCase().includes(q) ||
      (c.category || "").toLowerCase().includes(q);
    const filtered = constructs.filter(match);

    const out = [];
    const used = new Set();

    const recentIds = readRecent();
    const recent = recentIds
      .map((id) => filtered.find((c) => c.id === id))
      .filter(Boolean);
    if (recent.length) {
      out.push(["Recently used", recent]);
      recent.forEach((c) => used.add(c.id));
    }

    const custom = filtered.filter((c) => !c.is_seed && !used.has(c.id));
    if (custom.length) {
      out.push(["My custom constructs", custom]);
      custom.forEach((c) => used.add(c.id));
    }

    const byCategory = new Map();
    for (const c of filtered) {
      if (used.has(c.id)) continue;
      const cat = c.category || "Other";
      if (!byCategory.has(cat)) byCategory.set(cat, []);
      byCategory.get(cat).push(c);
    }
    for (const cat of [...byCategory.keys()].sort((a, b) => a.localeCompare(b))) {
      out.push([cat, byCategory.get(cat).sort((a, b) => a.name.localeCompare(b.name))]);
    }
    return out;
  }, [constructs, query]);

  const flat = useMemo(() => groups.flatMap(([, items]) => items), [groups]);

  useEffect(() => setActive(0), [query, open]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  // Keep the active option scrolled into view.
  useEffect(() => {
    const el = listRef.current?.querySelector('[data-active="true"]');
    el?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  function choose(c) {
    onChange(c.id);
    rememberRecent(c.id);
    setOpen(false);
    setQuery("");
  }

  function onKeyDown(e) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, flat.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (flat[active]) choose(flat[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  let index = -1; // running index across groups for keyboard highlight

  return (
    <div className="picker" ref={rootRef}>
      {!open ? (
        <button
          type="button"
          className="picker-display"
          aria-haspopup="listbox"
          aria-expanded="false"
          onClick={() => {
            setOpen(true);
            setTimeout(() => inputRef.current?.focus(), 0);
          }}
        >
          {selected ? (
            <>
              <span>{selected.name}</span>
              <span className="picker-meta">
                {selected.items.length} item{selected.items.length === 1 ? "" : "s"}
              </span>
            </>
          ) : (
            <span className="muted">Select a construct ({constructs.length} in library)</span>
          )}
          <span className="picker-caret" aria-hidden="true">▾</span>
        </button>
      ) : (
        <>
          <input
            ref={inputRef}
            type="text"
            role="combobox"
            aria-expanded="true"
            aria-autocomplete="list"
            className="picker-search"
            placeholder="Search by scale, construct, or category (e.g. empathy, GAD-7)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
          />
          <div className="picker-panel" role="listbox" ref={listRef}>
            {flat.length === 0 && (
              <p className="small muted picker-empty">
                No constructs match "{query}". Try a scale abbreviation or use + Custom construct.
              </p>
            )}
            {groups.map(([label, items]) => (
              <div key={label}>
                <div className="picker-group">{label}</div>
                {items.map((c) => {
                  index += 1;
                  const isActive = index === active;
                  return (
                    <div
                      key={c.id}
                      role="option"
                      aria-selected={c.id === value}
                      data-active={isActive || undefined}
                      className={
                        "picker-option" +
                        (isActive ? " active" : "") +
                        (c.id === value ? " selected" : "")
                      }
                      onMouseDown={(e) => {
                        e.preventDefault();
                        choose(c);
                      }}
                    >
                      <span className="picker-name">{c.name}</span>
                      <span className="picker-meta">
                        {c.category ? `${c.category} · ` : ""}
                        {c.items.length} item{c.items.length === 1 ? "" : "s"}
                        {c.verification_status !== "verified" ? " · unverified" : ""}
                      </span>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
