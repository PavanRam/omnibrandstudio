from prometheus_client import CollectorRegistry, Counter, Histogram

REGISTRY = CollectorRegistry()

llm_call_duration = Histogram(
    "omnibrand_llm_call_duration_seconds",
    "LLM call latency",
    ["agent", "model", "task"],
    registry=REGISTRY,
    buckets=[0.5, 1, 2, 5, 10, 30, 60],
)
llm_tokens_total = Counter(
    "omnibrand_llm_tokens_total",
    "Total tokens",
    ["agent", "model", "type"],  # type: input|output
    registry=REGISTRY,
)
campaign_duration = Histogram(
    "omnibrand_campaign_duration_seconds",
    "Total campaign pipeline duration",
    ["org_id", "status"],
    registry=REGISTRY,
    buckets=[30, 60, 90, 120, 150, 180, 240, 300],
)
campaign_cost_usd = Histogram(
    "omnibrand_campaign_cost_usd",
    "Total campaign LLM cost",
    ["org_id", "tier"],
    registry=REGISTRY,
    buckets=[0.10, 0.25, 0.41, 0.55, 0.75, 1.00, 2.00],
)
