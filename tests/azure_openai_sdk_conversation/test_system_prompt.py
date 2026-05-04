"""Tests for the system prompt builder."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.azure_openai_sdk_conversation.context.system_prompt import (
    SystemPromptBuilder,
)
from custom_components.azure_openai_sdk_conversation.core.config import AgentConfig
from custom_components.azure_openai_sdk_conversation.core.logger import AgentLogger


@pytest.fixture
def mock_config(hass):
    return AgentConfig.from_dict(
        hass,
        {
            "api_key": "test",
            "api_base": "https://test",
            "chat_model": "gpt-4o",
            "mcp_enabled": False,
        },
    )


@pytest.fixture
def logger(hass, mock_config):
    return AgentLogger(hass, mock_config)


@pytest.fixture
def builder(hass, mock_config, logger):
    return SystemPromptBuilder(hass, mock_config, logger)


@pytest.mark.anyio
async def test_build_full_prompt(builder, hass):
    """Test building full prompt without MCP."""
    builder._collector.collect = AsyncMock(
        return_value=[
            {
                "entity_id": "light.test",
                "name": "Test Light",
                "state": "on",
                "area": "Living",
            }
        ]
    )

    prompt = await builder.build()

    assert "Test Light" in prompt
    assert "light.test" in prompt
    assert "Living" in prompt


@pytest.mark.anyio
async def test_build_mcp_initial(hass, logger):
    """Test building MCP initial prompt."""
    config = AgentConfig.from_dict(
        hass,
        {
            "api_key": "test",
            "api_base": "https://test",
            "chat_model": "gpt-4o",
            "mcp_enabled": True,
        },
    )

    # Mock loop.create_task to avoid MCP starting in background
    hass.loop.create_task = MagicMock()

    builder = SystemPromptBuilder(hass, config, logger)
    builder._collector.collect = AsyncMock(return_value=[])

    with (
        patch.object(builder._mcp, "is_new_conversation", return_value=True),
        patch.object(
            builder._mcp, "build_initial_prompt", return_value="Initial Prompt"
        ),
    ):
        prompt = await builder.build(conversation_id="conv1")
        assert prompt == "Initial Prompt"


@pytest.mark.anyio
async def test_entity_context_contains_resolution_rules(builder):
    """Entity context must contain strict alias-resolution rules."""
    entities = [
        {
            "entity_id": "light.desk",
            "name": "Desk Lamp",
            "state": "off",
            "area": "Office",
            "aliases": ["desk lamp", "the desk light"],
        }
    ]
    context = SystemPromptBuilder._format_entity_context(entities)

    # Rules section must be present
    assert "Entity Resolution Rules" in context
    assert "NEVER" in context or "never" in context.lower()
    assert "alias" in context.lower() or "name" in context.lower()


@pytest.mark.anyio
async def test_entity_context_no_tool_call_without_resolution(builder):
    """Entity context must instruct model not to call tool before resolving entity."""
    entities = [
        {
            "entity_id": "light.desk",
            "name": "Desk Lamp",
            "state": "off",
            "area": "Office",
            "aliases": [],
        }
    ]
    context = SystemPromptBuilder._format_entity_context(entities)

    # Must contain instruction to not call tool without resolved target
    assert "do not" in context.lower() or "until you have resolved" in context.lower()


@pytest.mark.anyio
async def test_build_full_prompt_contains_alias_rules(builder):
    """Full prompt must embed alias-resolution rules."""
    builder._collector.collect = AsyncMock(
        return_value=[
            {
                "entity_id": "light.desk",
                "name": "Desk Lamp",
                "state": "off",
                "area": "Office",
                "aliases": ["desk lamp"],
            }
        ]
    )

    prompt = await builder.build()

    assert "Entity Resolution Rules" in prompt
    assert "desk lamp" in prompt.lower() or "Desk Lamp" in prompt


@pytest.mark.anyio
async def test_build_mcp_delta(hass, logger):
    """Test building MCP delta prompt."""
    config = AgentConfig.from_dict(
        hass,
        {
            "api_key": "test",
            "api_base": "https://test",
            "chat_model": "gpt-4o",
            "mcp_enabled": True,
        },
    )
    hass.loop.create_task = MagicMock()

    builder = SystemPromptBuilder(hass, config, logger)
    builder._collector.collect = AsyncMock(return_value=[])

    with patch.object(builder._mcp, "is_new_conversation", return_value=False):
        with patch.object(
            builder._mcp, "build_delta_prompt", return_value="Delta Prompt"
        ) as delta_mock:
            prompt = await builder.build(conversation_id="conv1")
            assert prompt == "Delta Prompt"
            delta_mock.assert_called_once_with(
                conversation_id="conv1",
                entities=[],
                base_prompt=config.system_prompt,
            )


@pytest.mark.anyio
async def test_build_mcp_delta_fallback_on_none(hass, logger):
    """When build_delta_prompt returns None (TTL expired), fall back to full context."""
    config = AgentConfig.from_dict(
        hass,
        {
            "api_key": "test",
            "api_base": "https://test",
            "chat_model": "gpt-4o",
            "mcp_enabled": True,
        },
    )
    hass.loop.create_task = MagicMock()

    entities = [
        {
            "entity_id": "light.desk_lamp",
            "name": "Desk Lamp",
            "state": "on",
            "area": "Office",
            "aliases": ["desk lamp"],
        }
    ]

    builder = SystemPromptBuilder(hass, config, logger)
    builder._collector.collect = AsyncMock(return_value=entities)

    with (
        patch.object(builder._mcp, "is_new_conversation", return_value=False),
        # Simulate TTL-expired conversation: MCP manager returns None
        patch.object(builder._mcp, "build_delta_prompt", return_value=None),
    ):
        prompt = await builder.build(conversation_id="conv_ttl_expired")
        # Must fall back to full context, not an empty/minimal message
        assert "light.desk_lamp" in prompt
        assert "Desk Lamp" in prompt
