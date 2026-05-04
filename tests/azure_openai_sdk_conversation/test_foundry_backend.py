"""Tests for backend routing and Foundry config handling."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components import conversation

from custom_components.azure_openai_sdk_conversation.core.agent import (
    AzureOpenAIConversationAgent,
)
from custom_components.azure_openai_sdk_conversation.core.config import AgentConfig
from custom_components.azure_openai_sdk_conversation.stats.metrics import RequestMetrics


@pytest.mark.anyio
async def test_config_parses_foundry_fields(hass):
    """AgentConfig should parse Foundry and backend fields from input dict."""
    config = AgentConfig.from_dict(
        hass,
        {
            "api_key": "k",
            "api_base": "https://example.openai.azure.com",
            "chat_model": "gpt-4o-mini",
            "llm_backend": "foundry",
            "foundry_enabled": True,
            "foundry_endpoint": "https://foundry.example/api/agent",
            "foundry_api_key": "fkey",
            "foundry_timeout": 42,
        },
    )

    assert config.llm_backend == "foundry"
    assert config.foundry_enabled is True
    assert config.foundry_endpoint == "https://foundry.example/api/agent"
    assert config.foundry_api_key == "fkey"
    assert config.foundry_timeout == 42


@pytest.mark.anyio
async def test_config_validate_requires_foundry_endpoint_when_enabled(hass):
    """Validation should fail if Foundry is enabled without an endpoint."""
    config = AgentConfig.from_dict(
        hass,
        {
            "api_key": "k",
            "api_base": "https://example.openai.azure.com",
            "chat_model": "gpt-4o-mini",
            "foundry_enabled": True,
            "foundry_endpoint": "",
        },
    )

    errors = config.validate()
    assert "foundry_endpoint is required when foundry_enabled is true" in errors


@pytest.mark.anyio
async def test_select_llm_client_prefers_foundry_in_auto_mode(hass):
    """Auto mode should prefer Foundry client when configured and enabled."""
    config = AgentConfig.from_dict(
        hass,
        {
            "api_key": "k",
            "api_base": "https://example.openai.azure.com",
            "chat_model": "gpt-4o-mini",
            "llm_backend": "auto",
            "foundry_enabled": True,
            "foundry_endpoint": "https://foundry.example/api/agent",
        },
    )

    agent = AzureOpenAIConversationAgent(hass, config)
    client, handler, use_responses = agent._select_llm_client()

    assert client is agent._foundry_client
    assert handler == "llm_foundry"
    assert use_responses is False


@pytest.mark.anyio
async def test_select_llm_client_falls_back_to_azure_when_foundry_missing(hass):
    """Explicit Foundry mode must safely fall back to Azure if not configured."""
    config = AgentConfig.from_dict(
        hass,
        {
            "api_key": "k",
            "api_base": "https://example.openai.azure.com",
            "chat_model": "gpt-4o-mini",
            "llm_backend": "foundry",
            "foundry_enabled": False,
        },
    )

    agent = AzureOpenAIConversationAgent(hass, config)
    client, handler, use_responses = agent._select_llm_client()

    assert client is agent._chat_client
    assert handler == "llm_chat"
    assert use_responses is False


@pytest.mark.anyio
async def test_process_with_llm_falls_back_to_azure_on_foundry_error(hass):
    """If Foundry runtime call fails, _process_with_llm should retry on Azure client."""
    config = AgentConfig.from_dict(
        hass,
        {
            "api_key": "k",
            "api_base": "https://example.openai.azure.com",
            "chat_model": "gpt-4o-mini",
            "llm_backend": "auto",
            "foundry_enabled": True,
            "foundry_endpoint": "https://foundry.example/api/agent",
            "tools_enable": False,
            "early_wait_enable": False,
            "sliding_window_enable": False,
            "mcp_enabled": False,
        },
    )

    agent = AzureOpenAIConversationAgent(hass, config)

    # Mock prompt builder so no entity collection side effects are involved.
    agent._prompt_builder.build = AsyncMock(return_value="system")

    foundry_client = MagicMock()
    foundry_client.effective_api_version = "foundry-bridge-v1"
    foundry_client.complete = AsyncMock(side_effect=RuntimeError("foundry down"))

    azure_client = MagicMock()
    azure_client.effective_api_version = "2025-03-01-preview"
    azure_client.complete = AsyncMock(
        return_value=("Fallback from Azure", {"prompt": 1, "completion": 2, "total": 3})
    )

    user_input = conversation.ConversationInput(
        text="Are there lights on?",
        context=MagicMock(),
        conversation_id="conv1",
        language="en",
    )
    metrics = RequestMetrics(
        timestamp="now",
        conversation_id="conv1",
        execution_time_ms=0.0,
        handler="unknown",
        original_text="Are there lights on?",
        normalized_text="Are there lights on?",
        success=True,
    )

    with patch.object(
        agent,
        "_select_llm_client",
        return_value=(foundry_client, "llm_foundry", False),
    ):
        with patch.object(agent, "_chat_client", azure_client):
            result = await agent._process_with_llm(
                user_input=user_input,
                normalized_text="Are there lights on?",
                metrics=metrics,
                start_time=time.perf_counter(),
            )

    assert result.response.speech["plain"]["speech"] == "Fallback from Azure"
    assert metrics.handler == "llm_chat"
    assert metrics.total_tokens == 3
    foundry_client.complete.assert_awaited_once()
    azure_client.complete.assert_awaited_once()
