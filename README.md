# RFP Agent Studio

A polished workspace for running **RFP responses with a team of Microsoft Foundry
(Azure AI Foundry) agents**. It **reuses existing agents** (an orchestrator that delegates
to specialized sub‑agents) and gives you a UI that clearly surfaces:

- 🧠 **Each individual sub‑agent's output** — see who did what, in real time.
- 📎 **Sources / citations** — the documents and links behind the answer.
- 📝 **A nicely formatted final answer** — rendered markdown with tables, headings, etc.

It ships with a **mock mode** so you can run the whole experience end‑to‑end without any
Azure credentials, then flip a flag to point at your real Foundry project.

```
React + Vite UI  ──HTTP/SSE──►  FastAPI backend  ──Azure AI Agents SDK──►  Foundry project
  • Chat (markdown)              • /api/agents                              (existing agents,
  • Agent Activity panel         • /api/threads                              reused by ID)
  • Sources panel                • /api/chat (SSE stream)
                                 • mock mode (USE_MOCK)
```

## Project layout

```
backend/    FastAPI app (Python) — Azure AI Agents SDK wrapper + mock provider
frontend/   React + Vite + TypeScript UI
```

## Prerequisites

- Python 3.9+
- Node.js 18+
- (Live mode only) An Azure AI Foundry project with one or more existing agents, and
  `az login` completed for `DefaultAzureCredential`.

## 1. Run the backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # defaults to USE_MOCK=true
uvicorn app.main:app --reload --port 8000
```

The API is now on `http://127.0.0.1:8000` (`/docs` for Swagger, `/api/health` for status).

## 2. Run the frontend

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The Vite dev server proxies `/api` to the backend, so no
extra config is needed. Try a suggestion chip or type your own RFP question and watch the
specialists work.

## Switching from mock to live Foundry

Edit `backend/.env`:

```ini
USE_MOCK=false
PROJECT_ENDPOINT=https://<your-resource>.services.ai.azure.com/api/projects/<project>
MAIN_AGENT_ID=asst_xxxxxxxx           # your orchestrator agent
CONNECTED_AGENT_IDS=asst_aaa,asst_bbb # optional: label connected sub-agents
MODEL_DEPLOYMENT=gpt-4o               # display only
```

Then `az login` and restart the backend. The header badge flips from **Mock mode** to
**Live Foundry** when `PROJECT_ENDPOINT` + `MAIN_AGENT_ID` are set and `USE_MOCK=false`.

### How sub‑agent output and sources are surfaced (live mode)

- The backend creates a thread, posts your message, and runs the **main agent**.
- It **polls the run** and walks `run.steps[*].step_details.tool_calls`. Connected‑agent
  tool calls become **Agent Activity** cards (name, status, output). Other tools
  (file search, Azure AI Search, functions) are surfaced as tool steps too.
- The final assistant message's `annotations` (file/url citations) become **Sources**.

The SDK shapes for connected agents differ across versions, so the parser is intentionally
defensive (`backend/app/foundry_client.py`). If a specific field isn't surfaced for your
setup, that file is the one place to adjust the mapping.

## API reference

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Status + mock/live flags |
| GET | `/api/agents` | List the agent team (main + connected) |
| POST | `/api/threads` | Create a conversation thread |
| POST | `/api/chat` | Send a message; **SSE stream** of `agent_step` / `token` / `sources` / `done` |
| GET | `/api/threads/{id}/messages` | Load history |

## Notes

- Agents are **reused, never created** — this app does not deploy or modify Foundry agents.
- Threads are kept in memory; restart clears history. Add a store if you need persistence.
- No secrets are committed: only `.env.example` is tracked, `.env` is git‑ignored.
