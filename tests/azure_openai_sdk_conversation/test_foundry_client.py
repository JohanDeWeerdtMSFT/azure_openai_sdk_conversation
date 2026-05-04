"""Tests for Foundry bridge client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from custom_components.azure_openai_sdk_conversation.core.config import AgentConfig
from custom_components.azure_openai_sdk_conversation.core.logger import AgentLogger
from custom_components.azure_openai_sdk_conversation.llm.foundry_client import (
    FoundryClient,
)


@pytest.fixture
def mock_config(hass):
    return AgentConfig.from_dict(
        hass,
        {
            "api_key": "test-key",
            "api_base": "https://test.openai.azure.com/",
            "chat_model": "gpt-4o-mini",
            "api_version": "2025-03-01-preview",
            "foundry_enabled": True,
            "foundry_endpoint": "https://foundry.example/api/agent",
            "foundry_api_key": "foundry-key",
            "foundry_timeout": 15,
        },
    )


@pytest.fixture
def logger(hass, mock_config):
    return AgentLogger(hass, mock_config)


@pytest.fixture
def client(hass, mock_config, logger):
    return FoundryClient(hass, mock_config, logger)


@pytest.mark.anyio
async def test_foundry_complete_success(client):
    """Foundry complete should parse content and token counts."""
    response = MagicMock()
    response.content = b'{"content":"hello","token_counts":{"prompt":2,"completion":3,"total":5}}'
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "content": "hello",
        "token_counts": {"prompt": 2, "completion": 3, "total": 5},
    }

    client._http = MagicMock()
    client._http.post = AsyncMock(return_value=response)

    text, tokens = await client.complete(
        [{"role": "user", "content": "hi"}],
        conversation_id="c1",
        user_message="hi",
    )

    assert text == "hello"
    assert tokens["total"] == 5


@pytest.mark.anyio
async def test_foundry_complete_with_tools_success(client):
    """Foundry complete_with_tools should return response dict and tokens."""
    response = MagicMock()
    response.content = b'{"content":"ok","tool_calls":[{"id":"1"}],"token_counts":{"prompt":1,"completion":1,"total":2}}'
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "content": "ok",
        "tool_calls": [{"id": "1"}],
        "token_counts": {"prompt": 1, "completion": 1, "total": 2},
    }

    client._http = MagicMock()
    client._http.post = AsyncMock(return_value=response)

    result, tokens = await client.complete_with_tools(
        [{"role": "user", "content": "do something"}],
        tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
        conversation_id="c2",
        user_message="do something",
    )

    assert result["content"] == "ok"
    assert len(result["tool_calls"]) == 1
    assert tokens["total"] == 2


@pytest.mark.anyio
async def test_foundry_timeout_raises_timeout_error(client):
    """Timeouts from transport should be normalized to TimeoutError."""
    client._http = MagicMock()
    client._http.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    with pytest.raises(TimeoutError):
        await client.complete([{"role": "user", "content": "hi"}])


@pytest.mark.anyio
async def test_foundry_http_error_bubbles(client):
    """HTTP status errors should be surfaced to caller."""
    response = MagicMock()
    response.status_code = 401
    response.text = "unauthorized"
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        message="401",
        request=MagicMock(),
        response=response,
    )

    client._http = MagicMock()
    client._http.post = AsyncMock(return_value=response)

    with pytest.raises(httpx.HTTPStatusError):
        await client.complete([{"role": "user", "content": "hi"}])


@pytest.mark.anyio
async def test_foundry_complete_parses_responses_usage_shape(client):
    """Responses API usage/input_tokens/output_tokens should be normalized."""
    response = MagicMock()
    response.content = b'{"output_text":"hello from responses","usage":{"input_tokens":7,"output_tokens":5,"total_tokens":12}}'
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "output_text": "hello from responses",
        "usage": {"input_tokens": 7, "output_tokens": 5, "total_tokens": 12},
    }

    client._http = MagicMock()
    client._http.post = AsyncMock(return_value=response)

    text, tokens = await client.complete([
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "hi"},
    ])

    assert text == "hello from responses"
    assert tokens == {"prompt": 7, "completion": 5, "total": 12}


@pytest.mark.anyio
async def test_foundry_complete_with_tools_normalizes_function_call_items(client):
    """Responses function_call output items should map to OpenAI-style tool_calls."""
    response = MagicMock()
    response.content = b'{"output":[{"type":"function_call","id":"fc_1","call_id":"call_1","name":"turn_on","arguments":"{\\"entity_id\\":\\"light.kitchen\\"}"}],"usage":{"input_tokens":3,"output_tokens":2,"total_tokens":5}}'
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "output": [
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "turn_on",
                "arguments": '{"entity_id":"light.kitchen"}',
            }
        ],
        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
    }

    client._http = MagicMock()
    client._http.post = AsyncMock(return_value=response)

    result, tokens = await client.complete_with_tools(
        [{"role": "user", "content": "turn on kitchen light"}],
        tools=[{"type": "function", "function": {"name": "turn_on", "parameters": {}}}],
    )

    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["id"] == "call_1"
    assert result["tool_calls"][0]["function"]["name"] == "turn_on"
    assert tokens == {"prompt": 3, "completion": 2, "total": 5}
