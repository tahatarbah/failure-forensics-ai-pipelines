# Technical Tutorial — Failure Forensics Tool

This guide walks through how the system works: architecture, data flow, extending detectors, and how to debug a real failure with the UI and API.

## 1. What the system does

You upload a **failed AI pipeline run** (LLM/agent trace or MLOps job artifacts). The backend:

1. **Detects format** and picks an ingest adapter
2. **Normalizes** the run into a unified model: Case → Run → Spans + Artifacts
3. **Marks the failure locus** (first/last error span)
4. **Runs detector packs** that emit ranked hypotheses with evidence pointers
5. Serves a **case detail UI**: timeline, hypotheses, evidence

Optional step: if `OPENAI_API_KEY` is set, **Explain** asks an LLM to write a short narrative grounded in those hypotheses (not a replacement for detectors).

## 2. Architecture

```
Browser (Next.js :3000)
    │  /api/*  (rewrite)
    ▼
FastAPI ( :8000 )
    ├── ingest/          format sniff + adapters
    ├── detectors/       LLM pack + MLOps pack
    ├── services/        create case, analyze, explain
    └── SQLite           cases, runs, spans, artifacts, hypotheses
```

| Path | Role |
|------|------|
| `backend/app/api/cases.py` | HTTP API |
| `backend/app/ingest/` | Adapters + auto-detect |
| `backend/app/detectors/` | Root-cause rules |
| `backend/app/services/analyze.py` | Persist + analyze orchestration |
| `frontend/app/` | Cases list + case workbench |
| `samples/` | Synthetic failing runs |

## 3. Run locally

**Terminal A — API**

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
set SAMPLES_DIR=..\samples
uvicorn app.main:app --reload --port 8000
```

**Terminal B — UI**

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. API docs: http://localhost:8000/docs

**Docker**

```bash
docker compose up --build
```

## 4. End-to-end walkthrough (UI)

1. Open the home page → **New case**
2. Click a demo card, e.g. **RAG miss**
3. On the case page, read the **stats row** (spans, errors, hypotheses, top confidence)
4. In **Timeline**, find the red pulsing **failure locus** (`vector_retriever`)
5. In **Hypotheses**, open **Retrieval miss / weak matches**
6. In **Evidence**, inspect the linked retriever inputs/outputs

Repeat with **Agent tool error** and **Training divergence** to see LLM vs MLOps detector packs.

## 5. Same flow via API

```bash
# Create a demo case
curl -X POST http://127.0.0.1:8000/api/cases/demo/rag_failure

# Or upload your own file
curl -X POST http://127.0.0.1:8000/api/cases ^
  -F "title=My failed RAG" ^
  -F "domain=auto" ^
  -F "file=@samples/rag_failure/trace.json"
```

Useful reads:

- `GET /api/cases/{id}` — full case (timeline + hypotheses + artifacts)
- `GET /api/cases/{id}/timeline`
- `GET /api/cases/{id}/hypotheses`
- `POST /api/cases/{id}/analyze` — re-run detectors
- `POST /api/cases/{id}/explain` — LLM narrative (needs API key)

## 6. Data model

```
Case
 └── Run (outcome, failure_span_id, raw_bundle_path)
      ├── Span[]   name, kind, status, attrs, parent_id, order_index
      └── Artifact[]  kind (log|prompt|response|metrics|error), content, span_id?
 └── Hypothesis[]  detector_id, title, confidence, rationale, evidence_refs[]
```

**Span kinds** you will see: `llm`, `tool`, `retrieval`, `agent`, `chain`, `train_epoch`, `eval`, `deploy`, …

**Evidence refs** look like `{ "type": "span", "id": "..." }` or `{ "type": "artifact", "id": "..." }`. The UI uses them to filter the Evidence pane.

## 7. Ingest pipeline

Entry: `ingest_file()` in `backend/app/ingest/__init__.py`.

1. `sniff_format(path)` → `langchain_trace` | `otlp_json` | `plain_logs` | `mlops_metrics`
2. Adapter parses → `IngestResult` (domain, spans, artifacts, failure_span_id)
3. `persist_ingest()` remaps span IDs to fresh UUIDs (so demos can be loaded repeatedly) and writes SQLite rows
4. `analyze_case()` runs detectors and stores hypotheses

### Supported inputs

| Format | Example | Domain hint |
|--------|---------|-------------|
| LangChain / LangSmith-like JSON | `samples/rag_failure/trace.json` | `llm_pipeline` |
| Generic / OTLP-ish spans JSON | `{ "spans": [...] }` | auto |
| Plain logs | `.log` / `.txt` | heuristic |
| MLOps metrics | `samples/training_failure/metrics.json` | `mlops` |

### Minimal LangChain-style shape

```json
{
  "id": "root",
  "name": "my_chain",
  "run_type": "chain",
  "child_runs": [
    {
      "id": "r1",
      "name": "vector_retriever",
      "run_type": "retriever",
      "status": "error",
      "error": "hit_count=0",
      "outputs": { "documents": [], "hit_count": 0 }
    }
  ]
}
```

### Minimal MLOps metrics shape

```json
{
  "baseline": { "val_accuracy": 0.91, "loss": 0.28 },
  "epochs": [
    { "epoch": 0, "loss": 0.5, "val_accuracy": 0.8 },
    { "epoch": 1, "loss": "NaN", "status": "error", "error": "diverged" }
  ],
  "exit_code": 1,
  "logs": "CUDA out of memory...\nTraceback..."
}
```

## 8. Detectors (how RCA works)

Registry: `backend/app/detectors/__init__.py` → `run_detectors(case, run, spans, artifacts)`.

Only detectors whose `domains` include the case domain run (or all if domain is `unknown`).

### LLM pack (`llm_pack.py`)

| Detector ID | Fires when |
|-------------|------------|
| `llm.empty_or_truncated_output` | Empty/truncated LLM completion |
| `llm.tool_schema_failure` | Tool error / validation / schema language |
| `llm.retrieval_miss` | Zero hits, empty docs, low scores |
| `llm.context_overflow` | Context/token limit messages |
| `llm.retry_storm` | Rate-limit / retry loops |
| `llm.guardrail_block` | Policy / moderation blocks |

### MLOps pack (`mlops_pack.py`)

| Detector ID | Fires when |
|-------------|------------|
| `mlops.traceback_exit` | Traceback / non-zero exit |
| `mlops.loss_divergence` | NaN/Inf or large loss spikes |
| `mlops.metric_regression` | Metric worse than baseline |
| `mlops.resource_oom` | OOM / CUDA / memory signals |
| `mlops.data_schema` | Missing feature / schema errors |
| `mlops.checkpoint_write` | Checkpoint / artifact write failure |

Hypotheses are sorted by **confidence** descending and stored with `rank`.

## 9. Add your own detector

1. Create a class in `llm_pack.py` or `mlops_pack.py`:

```python
class MyDetector:
    id = "llm.my_signal"
    domains = {"llm_pipeline"}

    def run(self, case, run, spans, artifacts):
        out = []
        for span in spans:
            if "my_failure_marker" in str(span.attrs).lower():
                out.append(
                    HypothesisDraft(
                        detector_id=self.id,
                        title="My custom failure",
                        confidence=0.8,
                        rationale=f"Marker found on `{span.name}`",
                        evidence_refs=[{"type": "span", "id": span.id}],
                    )
                )
        return out
```

2. Append an instance to `LLM_DETECTORS` or `MLOPS_DETECTORS`.
3. Restart the API (or rely on `--reload`).
4. `POST /api/cases/{id}/analyze` or upload a new case.

## 10. Add an ingest adapter

1. Implement `parse_*(path: Path) -> IngestResult` under `backend/app/ingest/adapters/`.
2. Teach `sniff_format()` how to recognize your files.
3. Wire it in `ingest_file()`.

Keep producing the same `SpanDraft` / `ArtifactDraft` shapes so detectors and UI stay unchanged.

## 11. Frontend notes

- Next.js rewrites `/api/*` → FastAPI (`next.config.js` `API_URL`).
- Home: upload + demos + case list (`app/page.tsx`).
- Case workbench: linked selection across timeline ↔ hypotheses ↔ evidence (`app/cases/[id]/page.tsx`).
- Styling: forensic ops theme in `app/globals.css` (Fraunces / Sora / JetBrains Mono).

## 12. Troubleshooting

| Symptom | Check |
|---------|--------|
| UI loads, demos fail | API down? `GET http://127.0.0.1:8000/api/health` |
| `Sample not found` | `SAMPLES_DIR` points at repo `samples/` |
| No hypotheses | Domain wrong? Span attrs missing signals detectors look for |
| Explain 400 | Set `OPENAI_API_KEY` |
| Duplicate span ID errors | Fixed by ID remapping in `persist_ingest`; pull latest code |
| CORS in browser | Confirm `cors_origins` includes `http://localhost:3000` |

## 13. Suggested learning path

1. Run the three demos and compare timelines
2. Read `samples/*/…` alongside the matching detector code
3. Upload a slightly edited sample (e.g. change `hit_count` to `3`) and re-analyze
4. Add one tiny detector and confirm it appears in the UI
5. Call `/explain` with an API key and compare narrative vs ranked hypotheses
