# Failure Forensics Tool for AI Pipelines

Web-first failure forensics for **LLM/agent pipelines** and **classical MLOps** runs. Upload a failed run bundle, reconstruct the timeline, and get ranked root-cause hypotheses with linked evidence.

## Quick start (Docker)

```bash
docker compose up --build
```

- UI: http://localhost:3000
- API: http://localhost:8000/docs

Optional LLM narrative:

```bash
# PowerShell
$env:OPENAI_API_KEY="sk-..."
docker compose up --build
```

## Local development

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
# from repo root samples path
set SAMPLES_DIR=../samples
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. The Next.js rewrite proxies `/api/*` to `http://localhost:8000`.

## Demo cases

From the home page:

| Demo | Domain | What you should see |
|------|--------|---------------------|
| RAG miss | LLM | Failure on retriever; retrieval-miss hypothesis |
| Agent tool error | LLM | Tool validation failure hypothesis |
| Training divergence | MLOps | NaN/loss spike, OOM/checkpoint signals |

## Supported ingest formats

- LangChain / LangSmith-style JSON traces
- Generic / OTLP-like span JSON (or JSONL)
- Plain `.log` / `.txt`
- MLOps `metrics.json` / CSV (+ optional baseline/config)

## API

- `POST /api/cases` — multipart upload (`file`, `title`, `domain`)
- `GET /api/cases` / `GET /api/cases/{id}`
- `POST /api/cases/{id}/analyze`
- `GET /api/cases/{id}/timeline`
- `GET /api/cases/{id}/hypotheses`
- `POST /api/cases/{id}/explain` — requires `OPENAI_API_KEY`
- `POST /api/cases/demo/{rag_failure|agent_failure|training_failure}`

## Project layout

```
backend/     FastAPI, SQLite, adapters, detectors
frontend/    Next.js App Router UI
samples/     Synthetic failing runs
docker-compose.yml
TUTORIAL.md  Technical walkthrough (architecture, API, extending detectors)
```

## Tutorial

See [TUTORIAL.md](TUTORIAL.md) for architecture, API usage, ingest formats, and how to add detectors.
