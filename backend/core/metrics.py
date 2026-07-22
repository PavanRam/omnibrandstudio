from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    PlatformCollector,
    ProcessCollector,
)

REGISTRY = CollectorRegistry()
# Include standard process + platform metrics in our custom registry
ProcessCollector(registry=REGISTRY)
PlatformCollector(registry=REGISTRY)

# ── HTTP ──────────────────────────────────────────────────────────────────────

http_requests_total = Counter(
    "omnibrand_http_requests_total",
    "Total HTTP requests received",
    ["method", "route", "status_code"],
    registry=REGISTRY,
)
http_request_duration = Histogram(
    "omnibrand_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    registry=REGISTRY,
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
)

# ── LLM ───────────────────────────────────────────────────────────────────────

llm_call_duration = Histogram(
    "omnibrand_llm_call_duration_seconds",
    "LLM call latency",
    ["agent", "model", "task"],
    registry=REGISTRY,
    buckets=[0.5, 1, 2, 5, 10, 30, 60],
)
llm_tokens_total = Counter(
    "omnibrand_llm_tokens_total",
    "Total tokens consumed",
    ["agent", "model", "type"],  # label values: input | output
    registry=REGISTRY,
)
llm_cost_usd_total = Counter(
    "omnibrand_llm_cost_usd_total",
    "Cumulative LLM cost in USD",
    ["agent", "model"],
    registry=REGISTRY,
)

# ── Campaign lifecycle ────────────────────────────────────────────────────────

campaign_duration = Histogram(
    "omnibrand_campaign_duration_seconds",
    "Total campaign pipeline wall-clock time",
    ["org_id", "status"],
    registry=REGISTRY,
    buckets=[30, 60, 90, 120, 150, 180, 240, 300],
)
campaign_cost_usd = Histogram(
    "omnibrand_campaign_cost_usd",
    "Total LLM cost per campaign",
    ["org_id", "tier"],
    registry=REGISTRY,
    buckets=[0.10, 0.25, 0.41, 0.55, 0.75, 1.00, 2.00],
)
campaigns_started_total = Counter(
    "omnibrand_campaigns_started_total",
    "Campaigns dequeued and started by the worker",
    ["org_id"],
    registry=REGISTRY,
)
campaigns_completed_total = Counter(
    "omnibrand_campaigns_completed_total",
    "Campaigns that finished (any terminal status)",
    ["org_id", "status"],  # status: completed | failed
    registry=REGISTRY,
)

# ── Queue / worker ────────────────────────────────────────────────────────────

queue_depth = Gauge(
    "omnibrand_queue_depth",
    "Number of messages currently in the campaigns queue",
    registry=REGISTRY,
)
dlq_messages_total = Counter(
    "omnibrand_dlq_messages_total",
    "Messages written to the dead-letter queue",
    registry=REGISTRY,
)

# ── Judge / routing ───────────────────────────────────────────────────────────

judge_latency = Histogram(
    "omnibrand_judge_latency_seconds",
    "Per-judge LLM evaluation latency",
    ["judge"],  # judge: claude | gpt4o | llama
    registry=REGISTRY,
    buckets=[1, 2, 5, 10, 20, 30, 60],
)
routing_decisions_total = Counter(
    "omnibrand_routing_decisions_total",
    "Routing decisions made by the confidence aggregator",
    ["decision"],  # decision: auto_approve | flag | auto_reject
    registry=REGISTRY,
)
