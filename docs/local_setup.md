# Local Setup

Steps to get this project running on a fresh machine, from cloning the repo to
generating content in the Streamlit UI. Assumes you already have a Python
environment set up and active.

---

## 1. Prerequisites

- Python 3.14 (matches the environment this project was built with)
- Git
- A Groq or OpenAI API key (see §3)
- Ports `8501` (Streamlit) and `8001` (RAG MCP server) free on localhost

---

## 2. Clone and install dependencies

```powershell
git clone https://github.com/PavanRam/omnibrandstudio
cd omnibrandstudio
pip install -r requirements.txt
```

Use `requirements-lock.txt` instead if you want the exact fully-pinned transitive
dependency set, rather than just the direct pins in
`requirements.txt`.

---

## 3. Configure environment variables

```powershell
Copy-Item .env.example .env
```

Then edit `.env`:

| Variable | Required | Notes |
|---|---|---|
| `LLM_PROVIDER` | yes | `groq` (default) or `openai` |
| `GROQ_API_KEY` | if provider is `groq` | |
| `OPENAI_API_KEY` | if provider is `openai` | |
| `GROQ_MODEL` | no | defaults to `llama-3.1-8b-instant` |
| `OPENAI_MODEL` | no | defaults to `gpt-4o-mini` |

`CHROMA_PATH` and `BRAND_MCP_SERVER_URL` in `.env.example` can be left as-is.

---

## 4. Build the local knowledge base

The cleaned/processed datasets (`datasets/processed/*.csv`, `datasets/processed/brand_guidelines/*.json`)
are already included in the repo — you don't need to download anything from
Kaggle or re-run notebooks to get started. What's *not* included is the vector
store itself.

```powershell
python -m src.rag.run_ingestion
```

This runs all four ingestion pipelines (brand guidelines, customer segments,
campaign performance, sentiment) and populates `knowledge_base/chroma/`. Takes
a couple of minutes; only needs to be run once (re-run it if you edit anything
under `datasets/processed/`).

---

## 5. Start the RAG MCP server

Content generation depends on this server running. Open a dedicated terminal
and leave it running:

```powershell
python -m src.rag.mcp_server
```

Serves at `http://localhost:8001/mcp`. If you skip this step, the Streamlit UI
will still load, but campaign submissions will fail at the context-assembly
step with a warning telling you to start it.

---

## 6. Launch the Streamlit app

In a second terminal:

```powershell
python -m streamlit run src/ui/app.py
```

Opens at `http://localhost:8501`.

---

## 7. Smoke test

1. Fill in a campaign brief (≥10 words), audience segment, pick at least one
   channel/language, brand tone, and campaign goal.
2. Submit. You should see it pass system validation → business validation →
   context assembly → content generation, and land on generated content tabs
   per channel/language.
3. If it stalls or errors at context assembly, check the MCP server terminal
   for errors and confirm it's still running on port 8001.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| UI shows a warning about the RAG MCP server being unreachable | §5 not started, or something else is bound to port 8001 |
| `business_validate` fails immediately with a validation-service error | Missing/invalid API key in `.env`, or wrong `LLM_PROVIDER` value |
| Ingestion (`run_ingestion`) reports 0 documents for a collection | `datasets/processed/` files missing or moved — confirm they exist.
| Port 8501 or 8001 already in use | Another process is bound to it — stop it, or override Streamlit's port with `--server.port` |
