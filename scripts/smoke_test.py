#!/usr/bin/env python
"""End-to-end validation for the lightweight or full local stack."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import urlopen

from dotenv import load_dotenv

load_dotenv()

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m~\033[0m"

ORG_ID = "00000000-0000-0000-0000-000000000001"
BRAND_ID = "00000000-0000-0000-0000-000000000002"
QUEUE = "campaigns:queue"
DLQ = "campaigns:dead_letter"
SUCCESS_STATUSES = {"published", "awaiting_review"}
FAILURE_STATUSES = {"failed", "cancelled"}


def _check(label: str, ok: bool, detail: str = "") -> bool:
    icon = PASS if ok else FAIL
    suffix = f" — {detail}" if detail else ""
    print(f"  {icon}  {label}{suffix}")
    return ok


def _warn(label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"  {WARN}  {label}{suffix}")


def _http_get(url: str, timeout: int = 5) -> tuple[int, str]:
    try:
        with urlopen(url, timeout=timeout) as response:
            return response.status, response.read().decode()
    except Exception as exc:
        return 0, str(exc)


def _redis_client():
    import redis

    return redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379"),
        decode_responses=True,
    )


def _postgres_dsn() -> str:
    raw = os.getenv("POSTGRES_DSN", "").replace("+asyncpg", "")
    if not raw:
        password = quote(os.environ["POSTGRES_PASSWORD"], safe="")
        return f"postgresql://omnibrand:{password}@localhost:5432/omnibrand"

    parts = urlsplit(raw)
    hostname = parts.hostname or "localhost"
    port = parts.port or 5432
    username = quote(parts.username or "omnibrand", safe="")
    password = quote(parts.password or "", safe="")
    host = "localhost" if hostname in {"postgres", "127.0.0.1"} else hostname
    netloc = f"{username}:{password}@{host}:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _new_uuid7() -> str:
    import uuid

    ts_ms = int(time.time() * 1_000) & 0xFFFF_FFFF_FFFF
    rnd = int.from_bytes(os.urandom(10), "big")
    rand_a = (rnd >> 68) & 0xFFF
    rand_b = rnd & 0x3FFF_FFFF_FFFF_FFFF
    value = (ts_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))


def check_api_health(base: str) -> bool:
    status, body = _http_get(f"{base}/health")
    return _check("API /health", status == 200 and "healthy" in body, f"HTTP {status}")


def check_metrics_endpoint(base: str) -> bool:
    status, body = _http_get(f"{base}/metrics")
    ok = status == 200 and "omnibrand_http_requests_total" in body
    return _check("API /metrics exposes application metrics", ok, f"HTTP {status}")


def check_prometheus_up(base: str) -> bool:
    status, _ = _http_get(f"{base}/-/healthy")
    return _check("Prometheus healthy", status == 200, f"HTTP {status}")


def check_prometheus_targets(base: str) -> bool:
    status, body = _http_get(f"{base}/api/v1/targets")
    if status != 200:
        return _check("Prometheus targets", False, f"HTTP {status}")
    data = json.loads(body)
    targets = data.get("data", {}).get("activeTargets", [])
    up_jobs = {target["labels"]["job"] for target in targets if target.get("health") == "up"}
    missing = {"omnibrand_api"} - up_jobs
    return _check(
        "Prometheus scrape targets UP",
        not missing,
        f"UP: {sorted(up_jobs)}" + (f" | MISSING: {sorted(missing)}" if missing else ""),
    )


def check_prometheus_rules(base: str) -> bool:
    status, body = _http_get(f"{base}/api/v1/rules")
    if status != 200:
        return _check("Prometheus alert rules loaded", False, f"HTTP {status}")
    groups = json.loads(body).get("data", {}).get("groups", [])
    count = sum(len(group.get("rules", [])) for group in groups)
    return _check(
        "Prometheus alert rules loaded",
        count > 0,
        f"{count} rules across {len(groups)} groups",
    )


def check_grafana(base: str) -> bool:
    status, _ = _http_get(f"{base}/api/health")
    return _check("Grafana healthy", status == 200, f"HTTP {status}")


def check_jaeger(base: str) -> bool:
    status, _ = _http_get(f"{base}/")
    return _check("Jaeger UI reachable", status == 200, f"HTTP {status}")


def check_metric_series(base: str, metric: str) -> bool:
    status, body = _http_get(f"{base}/api/v1/query?query={metric}")
    if status != 200:
        return _check(f"Metric {metric}", False, f"HTTP {status}")
    results = json.loads(body).get("data", {}).get("result", [])
    return _check(f"Metric {metric} has data", bool(results), f"{len(results)} series")


def _smoke_brief(index: int) -> dict:
    return {
        "brand_id": BRAND_ID,
        "objective": f"Lightweight smoke campaign {index}",
        "target_audience": "local acceptance testers",
        "key_messages": ["The lightweight pipeline remains functional"],
        "tone_override": None,
        "channels": ["email"],
        "locales": ["en"],
        "audience_segments": ["smoke"],
        "token_budget": 10000,
        "raw_text": "Create a concise email proving the local pipeline works.",
    }


def enqueue_campaigns(count: int) -> list[str]:
    import psycopg

    payloads: list[str] = []
    campaign_ids: list[str] = []
    rows: list[tuple[str, str]] = []
    for index in range(count):
        campaign_id = _new_uuid7()
        brief = _smoke_brief(index)
        campaign_ids.append(campaign_id)
        rows.append((campaign_id, json.dumps(brief)))
        payloads.append(
            json.dumps(
                {
                    "campaign_id": campaign_id,
                    "org_id": ORG_ID,
                    "brand_id": BRAND_ID,
                    "user_id": "",
                    "request_id": _new_uuid7(),
                    "brief": brief,
                }
            )
        )

    with (
        psycopg.connect(_postgres_dsn()) as connection,
        connection.cursor() as cursor,
    ):
        cursor.executemany(
            """
            INSERT INTO campaigns (id, org_id, brand_id, created_by, brief, status)
            VALUES (%s, %s, %s, NULL, %s::jsonb, 'queued')
            """,
            [(campaign_id, ORG_ID, BRAND_ID, brief) for campaign_id, brief in rows],
        )

    redis = _redis_client()
    try:
        for payload in payloads:
            redis.lpush(QUEUE, payload)
    finally:
        redis.close()
    return campaign_ids


def _campaign_statuses(campaign_ids: list[str]) -> dict[str, str]:
    import psycopg

    with (
        psycopg.connect(_postgres_dsn()) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT id::text, status FROM campaigns WHERE id = ANY(%s::uuid[])",
            (campaign_ids,),
        )
        return {campaign_id: status for campaign_id, status in cursor.fetchall()}


def _matching_dlq_ids(campaign_ids: list[str]) -> set[str]:
    expected = set(campaign_ids)
    redis = _redis_client()
    try:
        entries = redis.lrange(DLQ, 0, -1)
    finally:
        redis.close()

    matched: set[str] = set()
    for entry in entries:
        try:
            campaign_id = str(json.loads(entry).get("campaign_id", ""))
        except (TypeError, json.JSONDecodeError):
            continue
        if campaign_id in expected:
            matched.add(campaign_id)
    return matched


def wait_for_processing(campaign_ids: list[str], wait_secs: int) -> dict[str, str]:
    print(f"\n  Waiting up to {wait_secs}s for {len(campaign_ids)} campaigns to finish …")
    deadline = time.time() + wait_secs
    statuses: dict[str, str] = {}
    while time.time() < deadline:
        statuses = _campaign_statuses(campaign_ids)
        dlq_ids = _matching_dlq_ids(campaign_ids)
        summary = {
            status: list(statuses.values()).count(status)
            for status in set(statuses.values())
        }
        print(f"  Campaign states: {summary}  matching DLQ: {len(dlq_ids)}", end="\r")
        if dlq_ids or any(status in FAILURE_STATUSES for status in statuses.values()):
            break
        if len(statuses) == len(campaign_ids) and all(
            status in SUCCESS_STATUSES for status in statuses.values()
        ):
            break
        time.sleep(2)
    print()
    return statuses


def check_terminal_outcomes(campaign_ids: list[str], statuses: dict[str, str]) -> bool:
    dlq_ids = _matching_dlq_ids(campaign_ids)
    missing = set(campaign_ids) - set(statuses)
    failed = {
        campaign_id
        for campaign_id, status in statuses.items()
        if status in FAILURE_STATUSES
    }
    incomplete = {
        campaign_id
        for campaign_id, status in statuses.items()
        if status not in SUCCESS_STATUSES | FAILURE_STATUSES
    }
    ok = not (dlq_ids or missing or failed or incomplete)
    detail = (
        f"published={sum(status == 'published' for status in statuses.values())}, "
        f"awaiting_review={sum(status == 'awaiting_review' for status in statuses.values())}, "
        f"failed={len(failed)}, incomplete={len(incomplete)}, dlq={len(dlq_ids)}"
    )
    return _check("Campaigns reached a successful stable state", ok, detail)


def check_mailhog_delivery(mailhog: str, campaign_ids: list[str], *, required: bool) -> bool:
    published_ids = [
        campaign_id
        for campaign_id, status in _campaign_statuses(campaign_ids).items()
        if status == "published"
    ]
    if not published_ids:
        if required:
            return _check("MailHog received a published campaign", False, "no campaign published")
        _warn("MailHog publishing check skipped", "campaigns paused for human review")
        return True

    delivered: set[str] = set()
    for campaign_id in published_ids:
        status, body = _http_get(
            f"{mailhog}/api/v2/search?kind=containing&query={campaign_id}&limit=50"
        )
        if status == 200 and int(json.loads(body).get("total", 0)) > 0:
            delivered.add(campaign_id)
    return _check(
        "MailHog contains published campaign delivery",
        bool(delivered),
        f"{len(delivered)}/{len(published_ids)} published campaigns found",
    )


def run(count: int, wait_secs: int, *, full: bool, require_publishing: bool) -> int:
    api = os.getenv("API_BASE_URL", "http://localhost:8000")
    prometheus = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
    grafana = os.getenv("GRAFANA_URL", "http://localhost:3000")
    jaeger = os.getenv("JAEGER_URL", "http://localhost:16686")
    mailhog = os.getenv("MAILHOG_URL", "http://localhost:8025")
    failures: list[bool] = []

    print(f"\n═══ {'Full' if full else 'Lite'} pre-flight checks ═══")
    failures.append(not check_api_health(api))
    failures.append(not check_metrics_endpoint(api))
    if full:
        failures.extend(
            [
                not check_prometheus_up(prometheus),
                not check_grafana(grafana),
                not check_jaeger(jaeger),
                not check_prometheus_targets(prometheus),
                not check_prometheus_rules(prometheus),
            ]
        )
    else:
        _warn("External observability checks skipped", "lite mode")

    print(f"\n═══ Enqueuing {count} persisted smoke campaigns ═══")
    campaign_ids = enqueue_campaigns(count)
    print(f"  Enqueued: {campaign_ids[:3]}{'…' if count > 3 else ''}")

    statuses = wait_for_processing(campaign_ids, wait_secs)
    failures.append(not check_terminal_outcomes(campaign_ids, statuses))
    failures.append(
        not check_mailhog_delivery(mailhog, campaign_ids, required=require_publishing)
    )

    if full:
        print("\n═══ Post-run metric series checks ═══")
        for metric in [
            "omnibrand_campaigns_started_total",
            "omnibrand_campaigns_completed_total",
            "omnibrand_queue_depth",
            "omnibrand_http_requests_total",
        ]:
            failures.append(not check_metric_series(prometheus, metric))

    print("\n═══ Result ═══")
    failed = sum(failures)
    if failed:
        print(f"  {FAIL}  {failed}/{len(failures)} checks failed.")
        return 1
    print(f"  {PASS}  All {len(failures)} checks passed.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OmniBrand local acceptance gate")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--lite", action="store_true", help="Skip external observability services")
    mode.add_argument("--full", action="store_true", help="Require the full observability stack")
    parser.add_argument("--count", type=int, default=1, help="Number of campaigns (default 1)")
    parser.add_argument(
        "--wait-secs",
        type=int,
        default=300,
        help="Processing timeout (default 300)",
    )
    parser.add_argument(
        "--require-publishing",
        action="store_true",
        help="Fail unless a campaign publishes and appears in MailHog",
    )
    args = parser.parse_args()
    sys.exit(
        run(
            args.count,
            args.wait_secs,
            full=args.full,
            require_publishing=args.require_publishing,
        )
    )
