# DocPilot

[![codecov](https://codecov.io/gh/TOMATOsJr/project_3_docpilot/branch/main/graph/badge.svg)](https://codecov.io/gh/TOMATOsJr/project_3_docpilot)

DocPilot is a multi-model document intelligence platform for uploading, reading, querying, editing, and synthesizing documents with AI assistance. The project combines a FastAPI backend, a Vite + React frontend, PostgreSQL persistence, and a model gateway that can route requests across multiple LLM providers.

The system is designed around a document pipeline rather than a simple chat interface. Uploaded files are parsed, chunked, stored in PostgreSQL, embedded for retrieval, and then used for grounded Q&A or scoped edit proposals with diff-based review.

## What It Does

- Upload documents in formats such as PDF, DOCX, PPTX, Markdown, and plain text.
- View the stored text for each document in the center panel.
- Ask grounded questions over the active document or all uploaded documents.
- Propose edits to the active document and review the generated diff before accepting or rejecting it.
- Route requests to an appropriate model automatically, or pin a specific model manually from the UI.
- Generate synthesis answers across a selected document set.

## Architecture

### Frontend

The frontend lives in [frontend/src/App.tsx](frontend/src/App.tsx) and is built with React, TypeScript, and Vite. The interface has three main areas:

- Left pane: upload and document selection.
- Center pane: document content and diff preview.
- Right pane: chat, model selection, and edit resolution.

The Vite dev server proxies `/api` requests to the backend at `http://localhost:8000`.

### Backend

The backend is a FastAPI application defined in [backend/app/main.py](backend/app/main.py). It exposes routes for:

- Health checks
- Document upload, listing, download, and content retrieval
- Q&A requests
- Edit proposal, apply, and reject flows
- Cross-document synthesis

The backend is structured around services for ingestion, retrieval, orchestration, and model routing:

- [backend/app/services/ingest_service.py](backend/app/services/ingest_service.py) handles parsing, chunking, storing, and embedding documents.
- [backend/app/services/rag_engine.py](backend/app/services/rag_engine.py) handles retrieval and grounded answer generation.
- [backend/app/services/model_gateway.py](backend/app/services/model_gateway.py) abstracts provider access and dynamic model selection.
- [backend/app/services/agent_orchestrator.py](backend/app/services/agent_orchestrator.py) coordinates QA, edit, and synthesis flows.

### Persistence

PostgreSQL is used for document storage and chunk persistence. The repository is backed by the pgvector-enabled image defined in [docker-compose.yml](docker-compose.yml).

## Repository Layout

```text
project_3_docpilot/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── infrastructure/
│   │   └── services/
│   ├── scripts/
│   ├── pyproject.toml
│   └── benchmark_results.json
├── docs/
│   └── context_budgeting.md
├── frontend/
│   ├── src/
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml
└── README.md
```

## Prerequisites

- Python 3.12
- Node.js 18 or newer
- Docker and Docker Compose
- At least one LLM provider key, depending on the models you want to use

Recommended environment variables:

- `GEMINI_API_KEY`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GROQ_API_KEY`

The backend also reads its database connection and routing defaults from [backend/app/config.py](backend/app/config.py).

## Local Setup

### 1. Start PostgreSQL

```bash
docker compose up -d postgres
```

### 2. Start the backend

From the `backend` directory:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

If you prefer not to create a virtual environment manually, use your usual Python environment manager and install the same package set from [backend/pyproject.toml](backend/pyproject.toml).

### 3. Start the frontend

From the `frontend` directory:

```bash
cd frontend
npm install
npm run dev
```

Then open the Vite URL, usually `http://localhost:5173`.

## How To Use It

1. Upload one or more documents from the left pane.
2. Select a document to inspect its stored text.
3. Use Q&A mode to ask grounded questions about the active file or the full corpus.
4. Use Edit mode to request a rewrite of the active document, then accept or reject the diff.
5. Choose `Auto` to let DocPilot pick a model dynamically, or pick a specific allowed model manually.

## API Overview

All backend endpoints are mounted under `/api`.

- `GET /api/health`
- `GET /api/documents`
- `POST /api/documents/upload`
- `GET /api/documents/{document_id}/content`
- `GET /api/documents/{document_id}/download`
- `DELETE /api/documents/{document_id}`
- `POST /api/qa`
- `GET /api/qa/models`
- `POST /api/edits`
- `POST /api/edits/propose`
- `POST /api/edits/{command_id}/apply`
- `POST /api/edits/{command_id}/reject`
- `POST /api/synthesis`

## Verification

The backend API suite uses FastAPI's in-process test client and fakes for persistence and model services. It does not require PostgreSQL, Docker, provider keys, or network access:

```bash
cd backend
python -m pip install -e ".[dev]"
python -m pytest -q
python -m pytest -q --cov=app --cov-report=term-missing --cov-report=xml
```

GitHub Actions runs the backend tests and publishes coverage to Codecov on every push and pull request. Coverage is currently report-only; CI does not enforce a minimum percentage.

Authentication and rate limiting are not implemented yet, so this suite does not claim 401/403 or 429 behavior. Those cases should be added when those product controls are introduced.

The repository includes a lightweight ingestion smoke test:

```bash
cd backend
python scripts/phase2_smoke_test.py
```

If the backend, database, and model keys are configured correctly, the test should report that a document was stored and chunked successfully.

## Notes

- Context budgeting and retrieval behavior are documented in [docs/context_budgeting.md](docs/context_budgeting.md).
- The backend defaults to a local development origin list that includes `http://localhost:5173`.
- The frontend expects the backend to be reachable at `http://localhost:8000` during development via the Vite proxy.
