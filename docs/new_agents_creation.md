# Building Your Own Agents on Top of the Existing RAG Layer

This document helps in rebuilding the two post-validation LangGraph nodes
(`context_assembler`, `content_generator`) from scratch, while reusing the existing
RAG layer as-is.

---

## 1. Where you plug in

The graph up to and including business validation is unchanged. Your nodes take over
after that point.

```
system_validate → scan_input → business_validate → [ YOUR NODES ] → END
```

Current wiring (`src/agents/workflow.py`), for reference — replace the last two
`add_node` calls / edges with your own:

```python
builder.add_conditional_edges(
    "business_validate",
    _after_business,   # returns "assemble_context" if state["status"] == "approved", else "end"
    {"assemble_context": "assemble_context", "end": END},
)
```

**Contract you receive** — `WorkflowState` (`src/agents/state.py`) at the point your
first node runs:

```python
class WorkflowState(TypedDict):
    brief: dict              # validated CampaignBrief fields, see §4
    status: str               # will be "approved" when you take over
    persona: Optional[str]    # resolved by business_validate — one of 5 persona names, or None
    validation_error: Optional[str]
    # fields below are yours to populate:
    assembled_context: Optional[dict]
    generated_content: Optional[dict]
```

**Contract you must honor** — whatever nodes you add must update `state["status"]`
so the graph (or your own conditional edges) can route on it. The existing status
vocabulary (not enforced anywhere, just convention):
`approved → context_failed | context_assembled → generation_failed | completed`.
You're free to invent your own status values as long as your own conditional edge
functions agree with them.

`persona` may be `None` — the audience segment didn't match any of the 5 known
personas. Decide how your prompt/retrieval logic degrades in that case (the current
implementation falls back to `"General Audience"` in content generation and simply
omits the persona filter in retrieval).

---

## 2. Two ways to call RAG — pick one per node, or mix

### Option A — Direct calls (`RAGRetriever`)

Import and instantiate directly. Synchronous, in-process, no server required.

```python
from src.rag.retriever import RAGRetriever

retriever = RAGRetriever()  # opens a chromadb.PersistentClient — construct once, reuse
results = retriever.query_brand_guidelines(query="tone for luxury buyers", persona="High-Income Store Spender")
```

Simplest option if your nodes are plain synchronous Python (which LangGraph nodes
are expected to be).

### Option B — Via MCP

Requires the RAG MCP server running (`venv\Scripts\python -m src.rag.mcp_server`,
serves at `http://localhost:8001/mcp`). Same retrieval logic under the hood — MCP is
a network-facing wrapper around `RAGRetriever` plus one extra tool (`generate_content`)
that runs the LLM call server-side.

**When to pick which:** Option A is fewer moving parts (no
network hop) and is what's recommended unless you
specifically want RAG behind a network boundary

---

## 3. RAG query API reference

Four ChromaDB collections exist (`src/rag/config.py`):

| Constant | Collection name | Contents |
|---|---|---|
| `COLLECTION_BRAND` | `brand_guidelines` | brand identity, persona tone, channel templates, CTAs, localization rules, compliance rules |
| `COLLECTION_SEGMENTS` | `customer_segments` | 5 synthetic persona summaries + individual customer profile rows |
| `COLLECTION_CAMPAIGNS` | `campaign_performance` | campaign records + social ad performance rows |
| `COLLECTION_SENTIMENT` | `sentiment_insights` | individual tweets — **do not query directly for content gen**, see below |

Every `RAGRetriever` method returns `list[dict]` with keys `id`, `text`, `metadata`,
`distance` (direct calls) — the MCP tool wrappers return the same shape as a JSON
string, each item additionally exposing `rrf_score`/`rerank_score` when hybrid/rerank
is used. `text` is what you feed into your generation prompt.

### `query_brand_guidelines(query, n_results=5, persona=None, channel=None, language=None, content_type=None)`
Filter values:
- `persona`: one of the 5 names in §5
- `channel`: `Instagram | Facebook | LinkedIn | Email | Web | Catalog`
- `language`: `French | Spanish` (English is the unmarked default — no localization docs exist for it)
- `content_type`: `brand_identity | persona_tone | channel_template | cta_library | localization_rule | compliance_rule`

### `query_customer_segments(query, n_results=5, persona=None, dominant_channel=None, content_type=None)`
- `content_type="persona_summary"` → the 5 synthetic persona description docs (use `n_results=1` + a persona-matching query to map free-text audience descriptions to a canonical persona)
- `content_type="customer_profile"` → individual customer rows
- omit `content_type` to query both

### `query_campaign_data(query, n_results=5, channel=None, language=None, content_type=None)`
- `content_type="campaign_record"` → customer campaign history rows
- `content_type="ad_performance"` → social ad performance rows

### `query_sentiment(...)` — deprecated, avoid
Individual tweets are too short/context-free to be useful as retrieved RAG
documents. Use `SentimentAnalyzer` instead:

```python
from src.rag.sentiment_stats import SentimentAnalyzer
signal = SentimentAnalyzer().tone_signal()  # plain-English paragraph, aggregate stats
```

Equivalent MCP tool: `get_sentiment_signal()` (no params).

### `query_all(query, n_results=3)`
Convenience wrapper querying brand/segments/campaigns and returning a dict keyed by
collection name. Sentiment intentionally excluded.

### Retrieval mode knobs
Every method accepts `use_hybrid`, `use_reranker`, `use_mmr` (all default `True`) and
`fetch_k`

---

## 4. `CampaignBrief` fields available in `state["brief"]`

```python
class CampaignBrief(BaseModel):
    campaign_brief: str
    audience_segment: str
    target_channels: List[str]      # subset of Instagram/Facebook/LinkedIn/Email/Web/Catalog
    target_languages: List[str]     # subset of English/French/Spanish
    brand_tone: str
    campaign_goal: str
    restricted_words: List[str] = []
    validation_attempts: int = 0
    human_approved: bool = False
```

All fields are guaranteed present and non-empty (except `restricted_words`, which may
be `[]`) — `system_validate` already checked this before your nodes run.

---

## 5. The 5 personas (exact names, for filter values)

`High-Income Store Spender`, `Budget-Conscious Low Spender`, `Web-Savvy Mid-Tier Buyer`,
`Deal-Seeking Value Hunter`, `Highly Engaged Campaign Responder`.

Defined in `src/agents/nodes/business_validator.py::_PERSONAS` (full descriptions
there if you need them for prompt-building, e.g. injecting persona traits into your
generation prompt rather than only using the name).

---

## 6. MCP tool reference (if using Option B)

Server: `src/rag/mcp_server.py`, start with `venv\Scripts\python -m src.rag.mcp_server`,
serves at `http://localhost:8001/mcp`.

| Tool | Wraps | Notes |
|---|---|---|
| `retrieve_brand_guidelines(query, persona?, channel?, language?, content_type?, n_results=5)` | `RAGRetriever.query_brand_guidelines` | |
| `retrieve_customer_segments(query, persona?, content_type?, n_results=5)` | `RAGRetriever.query_customer_segments` | |
| `retrieve_campaign_data(query, channel?, language?, content_type?, n_results=5)` | `RAGRetriever.query_campaign_data` | |
| `retrieve_localization_rules(language, n_results=3)` | `query_brand_guidelines(content_type="localization_rule")` | convenience wrapper |
| `get_sentiment_signal()` | `SentimentAnalyzer.tone_signal()` | no params |
| `generate_content(prompt, channel, language="English")` | LLM call (server-side, `temperature=0.3`) | **you build the full prompt string yourself and pass it in** — this tool has no prompt-construction logic of its own; returns JSON string, or `{"error": ..., "raw": ...}` on malformed LLM output |

Retrieval-tool exceptions propagate to the
caller (you must catch them); `generate_content` catches its own exceptions and
returns a JSON error payload instead of raising.

---

## 7. Existing implementations, for reference only

`src/agents/nodes/context_assembler.py` and `src/agents/nodes/content_generator.py`
are the current implementations (MCP-based) — read them if you want a working
example, prompt-building structure, or per-channel/
per-language looping.
