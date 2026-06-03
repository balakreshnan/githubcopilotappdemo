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
  • Agent Activity panel         • /api/chat (SSE stream)                    reused by ID)
  • Sources panel                • mock mode (USE_MOCK)
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

Edit `backend/.env` (copy it from `.env.example` first):

```ini
# 1. Turn off mock mode
USE_MOCK=false

# 2. Point at your project
PROJECT_ENDPOINT=https://<your-resource>.services.ai.azure.com/api/projects/<project>

# 3. Identify the orchestrator agent BY NAME (matched case-insensitively)...
MAIN_AGENT_NAME=RFP Agent
#    ...or by id if you prefer:
# MAIN_AGENT_ID=asst_xxxxxxxxxxxx

# 4. (Optional) label connected sub-agents by name or id
# CONNECTED_AGENT_NAMES=Requirements Analyst,Compliance Reviewer,Pricing Estimator
# CONNECTED_AGENT_IDS=asst_aaa,asst_bbb

# 5. (Cross-tenant only) authenticate against the resource's Entra tenant
# AZURE_TENANT_ID=00000000-0000-0000-0000-000000000000

MODEL_DEPLOYMENT=gpt-4o   # display only
```

### Authentication (DefaultAzureCredential)

The backend authenticates with `DefaultAzureCredential` — no keys in the app. It tries, in
order: environment variables → Managed Identity → **Azure CLI** → Azure PowerShell → VS Code.
For local dev the simplest path is the Azure CLI:

```powershell
az login
az account set --subscription "<your-subscription>"   # if you have more than one
```

Make sure that signed-in identity has an **Azure AI Developer** / **Azure AI User** (or
equivalent) role on the Foundry project — specifically a role that grants the
`Microsoft.MachineLearningServices/workspaces/agents/action` data action, which is required
to *run* (not just list) agents. Then restart the backend:

```powershell
uvicorn app.main:app --reload --port 8000
```

> **Cross-tenant / guest users:** if the Foundry resource lives in a *different* Entra tenant
> than your default `az login` (common when you're a guest user in the resource's tenant), set
> `AZURE_TENANT_ID` in `backend/.env` to that resource tenant's id. The backend exports it so
> `DefaultAzureCredential` requests a token for the right tenant. Symptom of getting this wrong:
> listing agents works but running one fails with `403 ... does not have permissions for
> Microsoft.MachineLearningServices/workspaces/agents/action`.

The header badge flips from **Mock mode** to **Live Foundry** once `USE_MOCK=false` and
`PROJECT_ENDPOINT` + (`MAIN_AGENT_NAME` or `MAIN_AGENT_ID`) are set. Confirm with
`curl http://127.0.0.1:8000/api/health` → `"live_ready": true`.

> How agents are invoked: this app targets the current Foundry agent model in
> `azure-ai-projects` (2.x), where agents are versioned (ids look like `name:version`) and are
> run through the **OpenAI Responses API**. The backend calls
> `AIProjectClient.get_openai_client(agent_name=...)` (with `allow_preview=True`) and
> `responses.create(...)`, then parses the response's output items to surface each connected
> sub-agent / tool call and its citations. Supply `MAIN_AGENT_NAME` (a trailing `:version` on
> an id is stripped automatically).

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
| POST | `/api/chat` | Send a message; **SSE stream** of `agent_step` / `token` / `sources` / `done` |

## Notes

- Agents are **reused, never created** — this app does not deploy or modify Foundry agents.
- Threads are kept in memory; restart clears history. Add a store if you need persistence.
- No secrets are committed: only `.env.example` is tracked, `.env` is git‑ignored.
