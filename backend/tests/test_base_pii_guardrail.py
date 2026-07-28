"""PII guardrail at the traced_llm_call chokepoint.

Verifies that every agent gets PII protection automatically just by calling
traced_llm_call — no agent needs to remember to scrub itself. Both the
outbound `user`-role messages and the LLM's returned content are covered.
"""
import json

import httpx
from pipeline.agents import base


def _state() -> dict:
    return {"campaign_id": None, "org_id": "org-1", "brand_id": "brand-1"}


def _response_payload(content: str) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        "model": "gen-free",
        "_hidden_params": {"response_cost": 0.001},
    }


async def test_input_pii_redacted_before_http_call(httpx_mock):
    httpx_mock.add_response(json=_response_payload("clean response"))
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Contact jane.doe@acme.com about this."},
    ]
    await base.traced_llm_call(
        model="gen-free", messages=messages, task="content_generator", state=_state()
    )

    sent_messages = json.loads(httpx_mock.get_request().content)["messages"]
    assert sent_messages[1]["content"] == "Contact [REDACTED_EMAIL] about this."


async def test_multiple_user_messages_all_scrubbed(httpx_mock):
    httpx_mock.add_response(json=_response_payload("clean response"))
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "Original brief: SSN 123-45-6789."},
        {"role": "assistant", "content": "Draft content."},
        {"role": "user", "content": "Critique: email me at foo@bar.com"},
    ]
    await base.traced_llm_call(
        model="gen-free", messages=messages, task="content_generator", state=_state()
    )

    assert "[REDACTED_SSN]" in messages[1]["content"]
    assert "[REDACTED_EMAIL]" in messages[3]["content"]


async def test_system_and_assistant_messages_untouched(httpx_mock):
    httpx_mock.add_response(json=_response_payload("clean response"))
    messages = [
        {"role": "system", "content": "Reference SSN 123-45-6789 in examples."},
        {"role": "assistant", "content": "Prior draft mentioning foo@bar.com."},
        {"role": "user", "content": "Please continue."},
    ]
    await base.traced_llm_call(
        model="gen-free", messages=messages, task="content_generator", state=_state()
    )

    assert messages[0]["content"] == "Reference SSN 123-45-6789 in examples."
    assert messages[1]["content"] == "Prior draft mentioning foo@bar.com."


async def test_output_pii_redacted(httpx_mock):
    httpx_mock.add_response(json=_response_payload("Reach us at sales@acme.com anytime."))
    content, _usage = await base.traced_llm_call(
        model="gen-free",
        messages=[{"role": "user", "content": "hello"}],
        task="content_generator",
        state=_state(),
    )
    assert content == "Reach us at [REDACTED_EMAIL] anytime."


async def test_http_failure_fallback_uses_already_scrubbed_messages(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("boom"))
    content, usage = await base.traced_llm_call(
        model="gen-free",
        messages=[{"role": "user", "content": "Contact jane.doe@acme.com please."}],
        task="content_generator",
        state=_state(),
    )
    assert "jane.doe@acme.com" not in content
    assert "[REDACTED_EMAIL]" in content
    assert usage["cost"] == 0.0


async def test_clean_input_and_output_unchanged(httpx_mock):
    httpx_mock.add_response(json=_response_payload("clean response"))
    messages = [{"role": "user", "content": "Write a tagline for our product."}]
    content, _usage = await base.traced_llm_call(
        model="gen-free", messages=messages, task="content_generator", state=_state()
    )
    assert messages[0]["content"] == "Write a tagline for our product."
    assert content == "clean response"


async def test_guardrail_log_fires_for_input_and_output_redaction(httpx_mock, monkeypatch):
    httpx_mock.add_response(json=_response_payload("Reach us at sales@acme.com anytime."))

    warnings: list[dict] = []
    monkeypatch.setattr(
        base.log, "warning", lambda event, **kw: warnings.append({"event": event, **kw})
    )

    await base.traced_llm_call(
        model="gen-free",
        messages=[{"role": "user", "content": "email me at foo@bar.com"}],
        task="content_generator",
        state=_state(),
        agent="content_generator",
    )

    redaction_events = [w for w in warnings if w["event"] == "guardrail_pii_redacted"]
    directions = {w["direction"] for w in redaction_events}
    assert directions == {"input", "output"}
