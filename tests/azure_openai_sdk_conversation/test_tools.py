"""
Basic tests for tool calling functionality.

To run:
    pytest tests/test_tools.py
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.azure_openai_sdk_conversation.tools import (
    FunctionExecutor,
    ToolManager,
    ToolSchemaBuilder,
)


@pytest.fixture
def mock_hass():
    """Create mock Home Assistant instance."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_services = MagicMock(
        return_value={
            "light": {
                "turn_on": {
                    "description": "Turn on a light",
                    "fields": {
                        "entity_id": {
                            "description": "Entity ID",
                            "required": True,
                            "selector": {"entity": {"domain": "light"}},
                        },
                        "brightness": {
                            "description": "Brightness (0-255)",
                            "required": False,
                            "selector": {"number": {"min": 0, "max": 255}},
                        },
                    },
                },
                "turn_off": {
                    "description": "Turn off a light",
                    "fields": {
                        "entity_id": {
                            "description": "Entity ID",
                            "required": True,
                            "selector": {"entity": {"domain": "light"}},
                        },
                    },
                },
            },
            "switch": {
                "turn_on": {
                    "description": "Turn on a switch",
                    "fields": {
                        "entity_id": {
                            "description": "Entity ID",
                            "required": True,
                            "selector": {"entity": {"domain": "switch"}},
                        },
                    },
                },
            },
        }
    )

    hass.states = MagicMock()
    hass.states.get = MagicMock(
        return_value=MagicMock(
            entity_id="light.living_room",
            name="Living Room Light",
            state="off",
        )
    )

    return hass


@pytest.mark.anyio
async def test_schema_builder_basic(mock_hass):
    """Test basic schema building."""
    builder = ToolSchemaBuilder(mock_hass)

    tools = await builder.build_all_tools(allowed_domains={"light"})

    assert len(tools) > 0
    assert tools[0]["type"] == "function"
    assert "function" in tools[0]
    assert "name" in tools[0]["function"]
    assert "description" in tools[0]["function"]
    assert "parameters" in tools[0]["function"]


@pytest.mark.anyio
async def test_schema_builder_filters_domains(mock_hass):
    """Test domain filtering."""
    builder = ToolSchemaBuilder(mock_hass)

    # Only light domain
    light_tools = await builder.build_all_tools(allowed_domains={"light"})
    light_names = [t["function"]["name"] for t in light_tools]

    assert all(name.startswith("light_") for name in light_names)
    assert not any(name.startswith("switch_") for name in light_names)


@pytest.mark.anyio
async def test_function_executor_validation(mock_hass):
    """Test function executor validation."""
    executor = FunctionExecutor(
        hass=mock_hass,
        allowed_domains={"light", "switch"},
        max_calls_per_minute=30,
    )

    # Valid call
    valid_call = {
        "id": "call_123",
        "function": {
            "name": "light_turn_on",
            "arguments": '{"entity_id": "light.living_room"}',
        },
    }

    # Mock async_call
    mock_hass.services.async_call = AsyncMock()

    result = await executor.execute_tool_call(valid_call)

    assert result["success"] is True
    assert "light.living_room" in result["content"]
    mock_hass.services.async_call.assert_called_once()


@pytest.mark.anyio
async def test_function_executor_blacklist(mock_hass):
    """Test blacklisted service rejection."""
    executor = FunctionExecutor(
        hass=mock_hass,
        allowed_domains={"homeassistant"},
        max_calls_per_minute=30,
    )

    # Blacklisted service
    blacklisted_call = {
        "id": "call_456",
        "function": {
            "name": "homeassistant_restart",
            "arguments": "{}",
        },
    }

    result = await executor.execute_tool_call(blacklisted_call)

    assert result["success"] is False
    assert "blacklisted" in result["content"].lower()


@pytest.mark.anyio
async def test_function_executor_rate_limit(mock_hass):
    """Test rate limiting."""
    executor = FunctionExecutor(
        hass=mock_hass,
        allowed_domains={"light"},
        max_calls_per_minute=2,  # Very low limit for testing
    )

    mock_hass.services.async_call = AsyncMock()

    call_template = {
        "id": "call_{}",
        "function": {
            "name": "light_turn_on",
            "arguments": '{"entity_id": "light.test"}',
        },
    }

    # First two calls should succeed
    for i in range(2):
        call = call_template.copy()
        call["id"] = f"call_{i}"
        result = await executor.execute_tool_call(call)
        assert result["success"] is True

    # Third call should be rate limited
    call = call_template.copy()
    call["id"] = "call_3"
    result = await executor.execute_tool_call(call)
    assert result["success"] is False
    assert "rate limit" in result["content"].lower()


@pytest.mark.anyio
async def test_function_executor_invalid_entity(mock_hass):
    """Test invalid entity_id handling."""
    executor = FunctionExecutor(
        hass=mock_hass,
        allowed_domains={"light"},
        max_calls_per_minute=30,
    )

    # Mock state as None (non-existent entity)
    mock_hass.states.get = MagicMock(return_value=None)

    invalid_call = {
        "id": "call_789",
        "function": {
            "name": "light_turn_on",
            "arguments": '{"entity_id": "light.nonexistent"}',
        },
    }

    result = await executor.execute_tool_call(invalid_call)

    assert result["success"] is False
    assert (
        "invalid" in result["content"].lower()
        or "non-existent" in result["content"].lower()
    )


@pytest.mark.anyio
async def test_tool_manager_cache(mock_hass):
    """Test tool schema caching."""
    from custom_components.azure_openai_sdk_conversation.core.config import AgentConfig
    from custom_components.azure_openai_sdk_conversation.core.logger import AgentLogger

    config = AgentConfig.from_dict(
        mock_hass,
        {
            "api_key": "test",
            "api_base": "https://test.openai.azure.com",
            "chat_model": "gpt-4o",
            "tools_enable": True,
            "tools_whitelist": "light,switch",
        },
    )

    logger = AgentLogger(mock_hass, config)

    manager = ToolManager(hass=mock_hass, config=config, logger=logger)

    # First call - builds schema
    tools1 = await manager.get_tools_schema()
    assert len(tools1) > 0

    # Second call - uses cache
    tools2 = await manager.get_tools_schema()
    assert tools1 == tools2

    # Invalidate cache
    manager.invalidate_cache()

    # Third call - rebuilds
    tools3 = await manager.get_tools_schema()
    assert len(tools3) > 0


@pytest.mark.anyio
async def test_entity_id_description_contains_alias_guidance(mock_hass):
    """entity_id parameter descriptions must instruct alias-to-entity_id resolution."""
    builder = ToolSchemaBuilder(mock_hass)
    tools = await builder.build_all_tools(allowed_domains={"light"})

    for tool in tools:
        props = tool["function"]["parameters"].get("properties", {})
        if "entity_id" in props:
            desc = props["entity_id"]["description"].lower()
            assert "alias" in desc or "name" in desc, (
                f"entity_id description in {tool['function']['name']} must mention "
                "name/alias lookup"
            )
            assert "never" in desc or "only use" in desc or "do not" in desc, (
                f"entity_id description in {tool['function']['name']} must warn "
                "against guessing/fabricating entity_ids"
            )


@pytest.mark.anyio
async def test_entity_id_description_no_fabrication_warning(mock_hass):
    """entity_id parameter description must warn against fabricating IDs."""
    builder = ToolSchemaBuilder(mock_hass)
    tools = await builder.build_all_tools(allowed_domains={"light"})

    # Find light_turn_on (uses default parameters path with entity_id)
    light_on = next(
        (t for t in tools if t["function"]["name"] == "light_turn_on"), None
    )
    assert light_on is not None

    props = light_on["function"]["parameters"].get("properties", {})
    assert "entity_id" in props
    desc = props["entity_id"]["description"]
    # Must contain resolution instruction
    assert "look up" in desc.lower() or "entity list" in desc.lower()
    # Must warn against fabrication
    assert "never" in desc.lower() or "only use" in desc.lower()


@pytest.mark.anyio
async def test_alias_resolution_desk_lamp_scenario(mock_hass):
    """
    Regression test: schema descriptions must guide the model to resolve
    'desk lamp' to the correct entity_id via the alias/name columns.
    """
    builder = ToolSchemaBuilder(mock_hass)
    tools = await builder.build_all_tools(allowed_domains={"light"})

    # All tools targeting lights must carry proper entity_id guidance
    for tool in tools:
        if not tool["function"]["name"].startswith("light_"):
            continue
        props = tool["function"]["parameters"].get("properties", {})
        if "entity_id" not in props:
            continue
        desc = props["entity_id"]["description"]
        # Description should guide the model to look up by name/alias
        assert any(
            kw in desc.lower() for kw in ("alias", "name", "entity list", "look up")
        ), (
            f"{tool['function']['name']}: entity_id description must instruct "
            "alias/name lookup"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
