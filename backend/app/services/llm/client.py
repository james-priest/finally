"""The LLM call: LiteLLM via OpenRouter, Cerebras as the inference provider, structured output."""

import os

# Use the cost map bundled with litellm: otherwise importing it fetches one from GitHub, which slows
# startup and puts a network call in every test run. Must be set before the import.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from litellm import acompletion

from app.services.llm.mock import mock_reply
from app.services.llm.schema import LLMReply

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}


def mock_enabled() -> bool:
    return os.environ.get("LLM_MOCK", "").strip().lower() == "true"


async def call_llm(messages: list[dict]) -> LLMReply:
    """Ask the model for an LLMReply. Raises on network errors and on output that fails validation."""
    if mock_enabled():
        return mock_reply(messages[-1]["content"])
    response = await acompletion(
        model=MODEL,
        messages=messages,
        response_format=LLMReply,
        reasoning_effort="low",
        extra_body=EXTRA_BODY,
    )
    return LLMReply.model_validate_json(response.choices[0].message.content)
