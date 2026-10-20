import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router";
import { useWs } from "../context";
import { Icon } from "../icons";
import { DOC_GROUPS, searchDocs } from "./catalog";
import "./docs.css";

/** Reference for every warning and "not verified" reason, one article each (anchor = entry id). */
export function DocsPage() {
  const [q, setQ] = useState("");
  const loc = useLocation();
  const shown = useMemo(() => searchDocs(q), [q]);
  const target = loc.hash.slice(1);
  useEffect(() => {
    if (!target) return;
    document.getElementById(`doc-${target}`)?.scrollIntoView({ block: "start" });
  }, [target]);
  return (
    <section className="stack">
      <div className="page-head">
        <div>
          <h1>Docs</h1>
          <p className="muted">What each warning and “not verified” reason means, why it is there, and what to do.</p>
        </div>
        <input className="docs-search" type="search" placeholder="Search the docs" aria-label="Search the docs"
          value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="docs">
        <nav className="docs-toc tile soft" aria-label="Contents">
          {DOC_GROUPS.map((g) => {
            const items = shown.filter((d) => d.group === g);
            if (items.length === 0) return null;
            return (
              <div key={g}>
                <p className="eyebrow">{g}</p>
                {items.map((d) => (
                  <a key={d.id} href={`#${d.id}`} className={target === d.id ? "current" : ""}>{d.title}</a>
                ))}
              </div>
            );
          })}
        </nav>
        <div className="docs-body">
          {shown.length === 0 && <p className="muted">Nothing matches “{q}”.</p>}
          {shown.map((d) => (
            <article key={d.id} id={`doc-${d.id}`} className={`tile doc${target === d.id ? " target" : ""}`}>
              <p className="eyebrow">{d.group}</p>
              <h2>{d.title}</h2>
              <p className="doc-summary">{d.summary}</p>
              <div className="doc-cols">
                <div><h3>What it means</h3><p>{d.means}</p></div>
                <div><h3>Why it matters</h3><p>{d.why}</p></div>
                <div><h3>What to do</h3><ul>{d.fix.map((f, i) => <li key={i}>{f}</li>)}</ul></div>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

/** A small "?" that opens the docs page of a reason, when one explains it. */
export function DocLink({ id, label }: { id: string; label: string }) {
  const { ws } = useWs();
  return (
    <Link className="reason-help" to={`/w/${ws.slug}/docs#${id}`} title={`What this means: ${label}`} aria-label={`What this means: ${label}`}>
      <Icon name="info" size={15} />
    </Link>
  );
}
