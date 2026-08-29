"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  Artifact,
  CaseDetail,
  explainCase,
  getCase,
  reanalyze,
} from "@/lib/api";

export default function CasePage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [data, setData] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedSpan, setSelectedSpan] = useState<string | null>(null);
  const [selectedHyp, setSelectedHyp] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getCase(id)
      .then((d) => {
        setData(d);
        const fail = d.timeline.find((s) => s.is_failure_locus);
        setSelectedSpan(fail?.id || d.timeline[0]?.id || null);
        setSelectedHyp(d.hypotheses[0]?.id || null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"));
  }, [id]);

  const evidence: Artifact[] = useMemo(() => {
    if (!data) return [];
    const hyp = data.hypotheses.find((h) => h.id === selectedHyp);
    const refs = new Set((hyp?.evidence_refs || []).map((r) => r.id));
    const fromHyp = data.artifacts.filter(
      (a) => refs.has(a.id) || (a.span_id && refs.has(a.span_id))
    );
    if (fromHyp.length) return fromHyp;
    if (selectedSpan) {
      return data.artifacts.filter((a) => a.span_id === selectedSpan);
    }
    return data.artifacts.slice(0, 3);
  }, [data, selectedHyp, selectedSpan]);

  const stats = useMemo(() => {
    if (!data) return null;
    const failed = data.timeline.filter((s) => s.status === "error").length;
    const top = data.hypotheses[0];
    return {
      spans: data.timeline.length,
      failed,
      hyps: data.hypotheses.length,
      topConf: top ? `${Math.round(top.confidence * 100)}%` : "—",
    };
  }, [data]);

  async function onReanalyze() {
    setBusy(true);
    setError(null);
    try {
      const d = await reanalyze(id);
      setData(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Re-analyze failed");
    } finally {
      setBusy(false);
    }
  }

  async function onExplain() {
    setBusy(true);
    setError(null);
    try {
      const res = await explainCase(id);
      setData((prev) => (prev ? { ...prev, narrative: res.narrative } : prev));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Explain failed");
    } finally {
      setBusy(false);
    }
  }

  if (error && !data) {
    return <div className="error-banner">{error}</div>;
  }
  if (!data || !stats) {
    return <div className="loading-shell">Reconstructing case…</div>;
  }

  const failureSpan = data.timeline.find((s) => s.is_failure_locus);

  return (
    <div>
      {error && <div className="error-banner">{error}</div>}
      <div className="case-header">
        <div>
          <h1>{data.title}</h1>
          <div className="meta-row">
            <span className={`badge ${data.domain === "mlops" ? "mlops" : "llm"}`}>
              {data.domain === "mlops" ? "MLOps" : "LLM pipeline"}
            </span>
            <span className={`badge ${data.run?.outcome === "failed" ? "fail" : "ok"}`}>
              {data.run?.outcome || data.status}
            </span>
            {failureSpan && (
              <span className="muted">
                Locus: <strong style={{ color: "var(--danger)" }}>{failureSpan.name}</strong>
              </span>
            )}
          </div>
        </div>
        <div className="actions">
          <a className="btn btn-ghost" href="/">
            Back
          </a>
          <button className="btn" type="button" disabled={busy} onClick={onReanalyze}>
            Re-analyze
          </button>
          {data.explain_available && (
            <button className="btn btn-primary" type="button" disabled={busy} onClick={onExplain}>
              {busy ? "Working…" : "Explain"}
            </button>
          )}
        </div>
      </div>

      <div className="stats-row">
        <div className="stat">
          <div className="stat-label">Spans</div>
          <div className="stat-value">{stats.spans}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Errors</div>
          <div className="stat-value" style={{ color: stats.failed ? "var(--danger)" : undefined }}>
            {stats.failed}
          </div>
        </div>
        <div className="stat">
          <div className="stat-label">Hypotheses</div>
          <div className="stat-value">{stats.hyps}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Top confidence</div>
          <div className="stat-value">{stats.topConf}</div>
        </div>
      </div>

      {data.summary && (
        <p className="muted" style={{ marginTop: -8, marginBottom: 8 }}>
          {data.summary}
        </p>
      )}

      {data.narrative && <div className="narrative">{data.narrative}</div>}

      <div className="case-layout" style={{ marginTop: 14 }}>
        <section className="panel delay-1">
          <div className="panel-head">
            <h2>Timeline</h2>
            <span className="panel-kicker">Run graph</span>
          </div>
          <p className="lead">Steps in order. Failure locus pulses red.</p>
          <div className="timeline">
            {data.timeline.map((s) => (
              <div
                key={s.id}
                className={`t-item ${s.is_failure_locus ? "failure" : ""} ${
                  selectedSpan === s.id ? "selected" : ""
                }`}
                onClick={() => setSelectedSpan(s.id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") setSelectedSpan(s.id);
                }}
              >
                <div className="t-dot" />
                <div className="t-name">{s.name}</div>
                <div className="t-meta">
                  <span className="kind-chip">{s.kind}</span>
                  {s.status}
                  {s.is_failure_locus ? " · locus" : ""}
                </div>
              </div>
            ))}
            {data.timeline.length === 0 && <div className="empty">No spans ingested.</div>}
          </div>
        </section>

        <section className="panel delay-2">
          <div className="panel-head">
            <h2>Hypotheses</h2>
            <span className="panel-kicker">Ranked</span>
          </div>
          <p className="lead">Deterministic detectors with confidence and evidence links.</p>
          <div className="hyp-list">
            {data.hypotheses.map((h) => (
              <div
                key={h.id}
                className={`hyp ${selectedHyp === h.id ? "active" : ""}`}
                onClick={() => {
                  setSelectedHyp(h.id);
                  const spanRef = h.evidence_refs.find((r) => r.type === "span");
                  if (spanRef) setSelectedSpan(spanRef.id);
                }}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    setSelectedHyp(h.id);
                    const spanRef = h.evidence_refs.find((r) => r.type === "span");
                    if (spanRef) setSelectedSpan(spanRef.id);
                  }
                }}
              >
                <div className="hyp-top">
                  <div className="hyp-title">
                    <span className="hyp-rank">#{h.rank}</span>
                    {h.title}
                  </div>
                  <span className="badge">{(h.confidence * 100).toFixed(0)}%</span>
                </div>
                <div className="conf-track">
                  <div
                    className="conf-fill"
                    style={{ width: `${Math.round(h.confidence * 100)}%` }}
                  />
                </div>
                <div className="muted">{h.rationale}</div>
                <div className="t-meta" style={{ marginTop: 8 }}>
                  {h.detector_id}
                </div>
              </div>
            ))}
            {data.hypotheses.length === 0 && (
              <div className="empty">No hypotheses fired. Try re-analyzing or another bundle.</div>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>Evidence</h2>
            <span className="panel-kicker">Artifacts</span>
          </div>
          <p className="lead">Linked to the selected hypothesis or timeline step.</p>
          {evidence.length === 0 ? (
            <div className="empty">Select a hypothesis or timeline step.</div>
          ) : (
            evidence.map((a) => (
              <div key={a.id} className="evidence-block">
                <div className="t-meta" style={{ marginBottom: 6 }}>
                  <span className="kind-chip">{a.kind}</span>
                  {a.label}
                </div>
                <div className="evidence-wrap">
                  <pre className="evidence">{a.content}</pre>
                </div>
              </div>
            ))
          )}
        </section>
      </div>
    </div>
  );
}
