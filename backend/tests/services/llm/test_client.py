from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.services.llm import LLMReply
from app.services.llm.client import EXTRA_BODY, MODEL, call_llm


def fake_acompletion(content: str, calls: list[dict]):
    async def acompletion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    return acompletion


async def test_call_llm_requests_structured_output_from_cerebras(monkeypatch):
    monkeypatch.delenv("LLM_MOCK", raising=False)
    calls: list[dict] = []
    monkeypatch.setattr("app.services.llm.client.acompletion", fake_acompletion('{"message": "Hi"}', calls))
    messages = [{"role": "user", "content": "hello"}]

    reply = await call_llm(messages)

    assert reply == LLMReply(message="Hi")
    assert calls[0]["model"] == MODEL == "openrouter/openai/gpt-oss-120b"
    assert calls[0]["response_format"] is LLMReply
    assert calls[0]["extra_body"] == EXTRA_BODY == {"provider": {"order": ["cerebras"]}}
    assert calls[0]["messages"] is messages


async def test_call_llm_raises_on_malformed_output(monkeypatch):
    monkeypatch.delenv("LLM_MOCK", raising=False)
    monkeypatch.setattr("app.services.llm.client.acompletion", fake_acompletion("Sure, buying now!", []))
    with pytest.raises(ValidationError):
        await call_llm([{"role": "user", "content": "buy"}])
