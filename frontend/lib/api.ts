export type CaseSummary = {
  id: string;
  title: string;
  domain: string;
  status: string;
  summary: string | null;
  created_at: string;
  top_hypothesis: string | null;
  top_confidence: number | null;
};

export type Span = {
  id: string;
  parent_id: string | null;
  name: string;
  kind: string;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  attrs: Record<string, unknown>;
  order_index: number;
  is_failure_locus: boolean;
};

export type Hypothesis = {
  id: string;
  detector_id: string;
  title: string;
  confidence: number;
  rationale: string;
  evidence_refs: Array<{ type: string; id: string }>;
  rank: number;
};

export type Artifact = {
  id: string;
  span_id: string | null;
  kind: string;
  label: string;
  content: string;
  meta: Record<string, unknown>;
};

export type CaseDetail = {
  id: string;
  title: string;
  domain: string;
  status: string;
  summary: string | null;
  narrative: string | null;
  created_at: string;
  run: {
    id: string;
    started_at: string | null;
    ended_at: string | null;
    outcome: string;
    failure_span_id: string | null;
  } | null;
  timeline: Span[];
  hypotheses: Hypothesis[];
  artifacts: Artifact[];
  explain_available: boolean;
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export function listCases() {
  return api<CaseSummary[]>("/api/cases");
}

export function getCase(id: string) {
  return api<CaseDetail>(`/api/cases/${id}`);
}

export async function createCase(file: File, title: string, domain: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("title", title);
  form.append("domain", domain);
  return api<CaseDetail>("/api/cases", { method: "POST", body: form });
}

export function createDemo(sampleKey: string) {
  return api<CaseDetail>(`/api/cases/demo/${sampleKey}`, { method: "POST" });
}

export function reanalyze(id: string) {
  return api<CaseDetail>(`/api/cases/${id}/analyze`, { method: "POST" });
}

export function explainCase(id: string) {
  return api<{ narrative: string; source: string }>(`/api/cases/${id}/explain`, {
    method: "POST",
  });
}
