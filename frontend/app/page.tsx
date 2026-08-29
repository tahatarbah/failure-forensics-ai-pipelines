"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CaseSummary, createCase, createDemo, listCases } from "@/lib/api";

const DEMOS = [
  {
    key: "rag_failure",
    domain: "LLM",
    title: "RAG miss",
    blurb: "Zero-hit retriever, empty context",
  },
  {
    key: "agent_failure",
    domain: "LLM",
    title: "Agent tool error",
    blurb: "Schema validation on tool args",
  },
  {
    key: "training_failure",
    domain: "MLOps",
    title: "Training divergence",
    blurb: "NaN loss, OOM, checkpoint fail",
  },
] as const;

function formatWhen(iso: string) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function HomePage() {
  const router = useRouter();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [title, setTitle] = useState("");
  const [domain, setDomain] = useState("auto");
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await listCases();
      setCases(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load cases");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) {
      setError("Choose a run bundle to upload");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await createCase(file, title || file.name, domain);
      router.push(`/cases/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function onDemo(key: string) {
    setBusy(true);
    setError(null);
    try {
      const created = await createDemo(key);
      router.push(`/cases/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Demo failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="home-hero">
        <h1>Open a failed run. Get the root cause.</h1>
        <p>
          Ingest LLM/agent traces or MLOps job artifacts, rebuild the timeline, and rank
          evidence-backed failure hypotheses.
        </p>
      </section>

      <div className="grid-home">
        <section className="panel delay-1">
          <div className="panel-head">
            <h2>New case</h2>
            <span className="panel-kicker">Ingest</span>
          </div>
          <p className="lead">
            Drop a LangChain/OTLP JSON trace, training metrics JSON/CSV, or plain job log.
          </p>
          {error && <div className="error-banner">{error}</div>}
          <form onSubmit={onSubmit}>
            <div
              className={`dropzone ${drag ? "active" : ""} ${file ? "has-file" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDrag(true);
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDrag(false);
                const f = e.dataTransfer.files?.[0];
                if (f) setFile(f);
              }}
            >
              {file ? (
                <>
                  <span className="dropzone-title">{file.name}</span>
                  <span className="dropzone-hint">Ready to analyze — or drop another file</span>
                </>
              ) : (
                <>
                  <span className="dropzone-title">Drop run bundle</span>
                  <span className="dropzone-hint">
                    JSON, JSONL, CSV, LOG — or{" "}
                    <label className="browse-link">
                      browse
                      <input
                        type="file"
                        hidden
                        onChange={(e) => setFile(e.target.files?.[0] || null)}
                      />
                    </label>
                  </span>
                </>
              )}
            </div>
            <div className="field-row">
              <div className="field">
                <label>Title</label>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Optional case title"
                />
              </div>
              <div className="field">
                <label>Domain</label>
                <select value={domain} onChange={(e) => setDomain(e.target.value)}>
                  <option value="auto">Auto-detect</option>
                  <option value="llm_pipeline">LLM / agent</option>
                  <option value="mlops">MLOps</option>
                </select>
              </div>
            </div>
            <div className="form-actions">
              <button className="btn btn-primary" type="submit" disabled={busy}>
                {busy ? "Analyzing…" : "Analyze failure"}
              </button>
              {file && (
                <button
                  className="btn btn-ghost"
                  type="button"
                  disabled={busy}
                  onClick={() => setFile(null)}
                >
                  Clear file
                </button>
              )}
            </div>
          </form>

          <div className="section-divider">
            <span className="muted">Or load a synthetic failure</span>
            <div className="demo-grid">
              {DEMOS.map((d) => (
                <button
                  key={d.key}
                  className="demo-card"
                  type="button"
                  disabled={busy}
                  onClick={() => onDemo(d.key)}
                >
                  <div className="demo-label">{d.domain}</div>
                  <strong>{d.title}</strong>
                  <span>{d.blurb}</span>
                </button>
              ))}
            </div>
          </div>
        </section>

        <section className="panel delay-2">
          <div className="panel-head">
            <h2>Recent cases</h2>
            <span className="panel-kicker">{cases.length} stored</span>
          </div>
          <p className="lead">Resume a prior investigation.</p>
          {cases.length === 0 ? (
            <div className="empty">No cases yet. Upload a bundle or open a demo.</div>
          ) : (
            <ul className="case-list">
              {cases.map((c) => (
                <li key={c.id}>
                  <a className="case-item" href={`/cases/${c.id}`}>
                    <div className="case-item-top">
                      <div className="case-title">{c.title}</div>
                      <span className={`badge ${c.domain === "mlops" ? "mlops" : "llm"}`}>
                        {c.domain === "mlops" ? "MLOps" : "LLM"}
                      </span>
                    </div>
                    <div className="muted">
                      {c.top_hypothesis
                        ? `${c.top_hypothesis}${
                            c.top_confidence != null
                              ? ` · ${(c.top_confidence * 100).toFixed(0)}%`
                              : ""
                          }`
                        : c.summary || c.status}
                    </div>
                    <div className="t-meta" style={{ marginTop: 6 }}>
                      {formatWhen(c.created_at)} · {c.status}
                    </div>
                  </a>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
