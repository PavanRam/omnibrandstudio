#!/usr/bin/env python
"""
Structured local validation driver — Phase 5 of T0 observability hardening.

Pushes N dummy campaigns to the Redis queue, waits for processing, then
checks that expected observability signals are present.  Exits 0 on pass,
non-zero on failure.

Usage:
    uv run python scripts/smoke_test.py [--count N] [--wait-secs S]

Requirements:
    docker compose up (all services healthy) + worker running
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Minimal inline Redis + HTTP clients so the script has no extra deps
# ---------------------------------------------------------------------------

def _redis_lpush(items: list[str], queue: str = "campaigns:queue") -> None:
    import redis  # type: ignore[import]
    import os
    url = os.getenv("REDIS_URL", "redis://localhost:6379")
    r = redis.from_url(url, decode_responses=True)
    for item in items:
        r.lpush(queue, item)
    r.close()


def _redis_llen(key: str) -> int:
    import redis
    import os
    url = os.getenv("REDIS_URL", "redis://localhost:6379")
    r = redis.from_url(url, decode_responses=True)
    n = r.llen(key)
    r.close()
    return int(n)


def _http_get(url: str, timeout: int = 5) -> tuple[int, str]:
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode()
    except Exception as exc:
        return 0, str(exc)


# ---------------------------------------------------------------------------
# UUIDv7 (no extra deps — mirrors backend/core/ids.py)
# ---------------------------------------------------------------------------

def _new_uuid7() -> str:
    import os, time, uuid as _u
    ts_ms = int(time.time() * 1_000) & 0xFFFF_FFFF_FFFF
    rnd = int.from_bytes(os.urandom(10), "big")
    rand_a = (rnd >> 68) & 0xFFF
    rand_b = rnd & 0x3FFF_FFFF_FFFF_FFFF
    val = (ts_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(_u.UUID(int=val))


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m~\033[0m"


def _check(label: str, ok: bool, detail: str = "") -> bool:
    icon = PASS if ok else FAIL
    line = f"  {icon}  {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    return ok


# ---------------------------------------------------------------------------
# Validation steps
# ---------------------------------------------------------------------------

def check_api_health(base: str) -> bool:
    status, body = _http_get(f"{base}/health")
    ok = status == 200 and "healthy" in body
    return _check("API /health", ok, f"HTTP {status}")


def check_metrics_endpoint(base: str) -> bool:
    status, body = _http_get(f"{base}/metrics")
    ok = status == 200 and "omnibrand_http_requests_total" in body
    return _check("API /metrics exposes omnibrand metrics", ok, f"HTTP {status}")


def check_prometheus_up(prom: str) -> bool:
    status, body = _http_get(f"{prom}/-/healthy")
    ok = status == 200
    return _check("Prometheus healthy", ok, f"HTTP {status}")


def check_prometheus_targets(prom: str) -> bool:
    status, body = _http_get(f"{prom}/api/v1/targets")
    if status != 200:
        return _check("Prometheus targets", False, f"HTTP {status}")
    data = json.loads(body)
    targets = data.get("data", {}).get("activeTargets", [])
    up_jobs = {t["labels"]["job"] for t in targets if t.get("health") == "up"}
    expected = {"omnibrand_api"}
    missing = expected - up_jobs
    ok = len(missing) == 0
    detail = f"UP: {sorted(up_jobs)}" + (f" | MISSING: {sorted(missing)}" if missing else "")
    return _check("Prometheus scrape targets UP", ok, detail)


def check_prometheus_rules(prom: str) -> bool:
    status, body = _http_get(f"{prom}/api/v1/rules")
    if status != 200:
        return _check("Prometheus alert rules loaded", False, f"HTTP {status}")
    data = json.loads(body)
    groups = data.get("data", {}).get("groups", [])
    rule_count = sum(len(g.get("rules", [])) for g in groups)
    ok = rule_count > 0
    return _check("Prometheus alert rules loaded", ok, f"{rule_count} rules across {len(groups)} groups")


def check_grafana_up(graf: str) -> bool:
    status, _ = _http_get(f"{graf}/api/health")
    return _check("Grafana healthy", status == 200, f"HTTP {status}")


def check_grafana_dashboards(graf: str) -> bool:
    status, body = _http_get(f"{graf}/api/search?type=dash-db&limit=20")
    if status != 200:
        return _check("Grafana dashboards provisioned", False, f"HTTP {status}")
    boards = json.loads(body)
    titles = [b["title"] for b in boards]
    expected_titles = {
        "Campaign Operations", "LLM and Judge Quality",
        "Infrastructure Health", "Business KPIs",
    }
    present = expected_titles & set(titles)
    ok = len(present) == 4
    return _check(
        "Grafana dashboards provisioned (4/4)",
        ok,
        f"{sorted(present)}",
    )


def check_jaeger_up(jaeger: str) -> bool:
    status, _ = _http_get(f"{jaeger}/")
    return _check("Jaeger UI reachable", status == 200, f"HTTP {status}")


def enqueue_campaigns(count: int) -> list[str]:
    campaign_ids = []
    payloads = []
    for i in range(count):
        cid = _new_uuid7()
        campaign_ids.append(cid)
        task = {
            "campaign_id": cid,
            "org_id": "00000000-0000-0000-0000-000000000001",
            "brand_id": "00000000-0000-0000-0000-000000000002",
            "user_id": "smoke-test",
            "request_id": _new_uuid7(),
        }
        payloads.append(json.dumps(task))

    _redis_lpush(payloads)
    return campaign_ids


def wait_for_processing(campaign_ids: list[str], wait_secs: int) -> bool:
    """Poll the DLQ to detect failures; just wait for the queue to drain."""
    QUEUE = "campaigns:queue"
    DLQ   = "campaigns:dead_letter"
    print(f"\n  Waiting up to {wait_secs}s for {len(campaign_ids)} campaigns to process …")
    deadline = time.time() + wait_secs
    while time.time() < deadline:
        depth = _redis_llen(QUEUE)
        dlq   = _redis_llen(DLQ)
        print(f"  Queue depth: {depth}  DLQ: {dlq}", end="\r")
        if depth == 0:
            print()
            _check("All campaigns dequeued", True, f"DLQ={dlq}")
            return dlq == 0
        time.sleep(2)
    print()
    remaining = _redis_llen(QUEUE)
    return _check("All campaigns dequeued within timeout", remaining == 0, f"still {remaining} remaining")


def check_metric_series(prom: str, metric: str) -> bool:
    status, body = _http_get(f"{prom}/api/v1/query?query={metric}")
    if status != 200:
        return _check(f"Metric {metric}", False, f"HTTP {status}")
    data = json.loads(body)
    results = data.get("data", {}).get("result", [])
    return _check(f"Metric {metric} has data", len(results) > 0, f"{len(results)} series")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(count: int, wait_secs: int) -> int:
    import os
    api_base  = os.getenv("API_BASE_URL",  "http://localhost:8000")
    prom_base = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
    graf_base = os.getenv("GRAFANA_URL",    "http://localhost:3000")
    jaeger_ui = os.getenv("JAEGER_URL",     "http://localhost:16686")

    failures: list[bool] = []

    print("\n═══ Pre-flight service checks ═══")
    failures.append(not check_api_health(api_base))
    failures.append(not check_prometheus_up(prom_base))
    failures.append(not check_grafana_up(graf_base))
    failures.append(not check_jaeger_up(jaeger_ui))

    print("\n═══ Metrics endpoint ═══")
    failures.append(not check_metrics_endpoint(api_base))

    print("\n═══ Prometheus configuration ═══")
    failures.append(not check_prometheus_targets(prom_base))
    failures.append(not check_prometheus_rules(prom_base))

    print("\n═══ Grafana dashboards ═══")
    failures.append(not check_grafana_dashboards(graf_base))

    print(f"\n═══ Enqueuing {count} dummy campaigns ═══")
    campaign_ids = enqueue_campaigns(count)
    print(f"  Enqueued: {campaign_ids[:3]}{'…' if count > 3 else ''}")

    print("\n═══ Processing wait ═══")
    failures.append(not wait_for_processing(campaign_ids, wait_secs))

    print("\n═══ Post-run metric series checks ═══")
    for metric in [
        "omnibrand_campaigns_started_total",
        "omnibrand_campaigns_completed_total",
        "omnibrand_queue_depth",
        "omnibrand_http_requests_total",
    ]:
        failures.append(not check_metric_series(prom_base, metric))

    print("\n═══ Result ═══")
    failed = sum(failures)
    total = len(failures)
    if failed == 0:
        print(f"  {PASS}  All {total} checks passed — stack is observability-ready.")
        return 0
    else:
        print(f"  {FAIL}  {failed}/{total} checks failed.")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OmniBrand T0 structured validation")
    parser.add_argument("--count", type=int, default=20, help="Number of dummy campaigns (default 20)")
    parser.add_argument("--wait-secs", type=int, default=60, help="Max seconds to wait for processing (default 60)")
    args = parser.parse_args()
    sys.exit(run(args.count, args.wait_secs))
