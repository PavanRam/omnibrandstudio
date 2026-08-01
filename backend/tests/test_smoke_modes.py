from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_smoke_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "smoke_test.py"
    spec = importlib.util.spec_from_file_location("smoke_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_terminal_outcomes_accept_published_and_review_pause(monkeypatch) -> None:
    smoke = _load_smoke_module()
    monkeypatch.setattr(smoke, "_matching_dlq_ids", lambda _ids: set())

    assert smoke.check_terminal_outcomes(
        ["campaign-a", "campaign-b"],
        {"campaign-a": "published", "campaign-b": "awaiting_review"},
    )


def test_terminal_outcomes_reject_failed_campaign(monkeypatch) -> None:
    smoke = _load_smoke_module()
    monkeypatch.setattr(smoke, "_matching_dlq_ids", lambda _ids: set())

    assert not smoke.check_terminal_outcomes(
        ["campaign-a"],
        {"campaign-a": "failed"},
    )


def test_publishing_can_be_required(monkeypatch) -> None:
    smoke = _load_smoke_module()
    monkeypatch.setattr(
        smoke,
        "_campaign_statuses",
        lambda _ids: {"campaign-a": "awaiting_review"},
    )

    assert smoke.check_mailhog_delivery("http://mailhog", ["campaign-a"], required=False)
    assert not smoke.check_mailhog_delivery(
        "http://mailhog",
        ["campaign-a"],
        required=True,
    )
