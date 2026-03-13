"""Tests for the MCP manager."""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.azure_openai_sdk_conversation.context.mcp_manager import (
    MCPManager,
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
        },
    )


@pytest.fixture
def logger(hass, mock_config):
    return AgentLogger(hass, mock_config)


@pytest.fixture
def manager(hass, logger):
    return MCPManager(hass, ttl_seconds=3600, logger=logger)


@pytest.mark.anyio
async def test_mcp_manager_initial_and_delta(manager):
    conv_id = "test_conv"
    entities = [
        {"entity_id": "light.test", "name": "Light", "state": "off", "area": "Kitchen"}
    ]

    # Initial
    assert manager.is_new_conversation(conv_id) is True
    prompt = manager.build_initial_prompt(conv_id, entities, "Base")
    assert "Base" in prompt
    assert "Current time:" in prompt
    assert "Light" in prompt
    assert manager.is_new_conversation(conv_id) is False

    # Delta - no change still returns a complete follow-up prompt
    delta = manager.build_delta_prompt(conv_id, entities, "Base")
    assert "Base" in delta
    assert "Current time:" in delta
    assert "Entity Map" in delta
    assert "None." in delta

    # Delta - state change
    entities[0]["state"] = "on"
    delta = manager.build_delta_prompt(conv_id, entities, "Base")
    assert "Base" in delta
    assert "Current time:" in delta
    assert "Changed entities" in delta
    assert "light.test" in delta
    # Entity map must also be present in state-change delta
    assert "Entity Map" in delta

    # Delta - removed entity
    delta = manager.build_delta_prompt(conv_id, [], "Base")
    assert "Removed entities: light.test" in delta


@pytest.mark.anyio
async def test_mcp_manager_cleanup(manager):
    conv_id = "old_conv"
    manager.build_initial_prompt(conv_id, [], "Base")

    # Backdate last update
    manager._last_updated[conv_id] = datetime.now(timezone.utc) - timedelta(
        seconds=4000
    )

    await manager._cleanup_old_conversations()
    assert manager.is_new_conversation(conv_id) is True


def test_mcp_manager_stats(manager):
    manager.build_initial_prompt(
        "c1", [{"entity_id": "e1", "name": "n1", "state": "s1"}], "B"
    )
    stats = manager.get_stats()
    assert stats["active_conversations"] == 1
    assert stats["total_entities_tracked"] == 1


# ---------------------------------------------------------------------------
# Regression tests: entity context preserved across multi-turn conversations
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delta_always_includes_entity_map_for_resolution(manager):
    """Entity map (id, name, aliases) must be present in every delta prompt.

    Regression for: model loses entity map on turn 2+ when no state changed,
    causing 'turn off desk lamp' to fail because the alias is unknown.
    """
    conv_id = "desk_lamp_conv"
    entities = [
        {
            "entity_id": "light.desk_lamp",
            "name": "Desk Lamp",
            "state": "on",
            "area": "Office",
            "aliases": ["desk lamp", "office lamp"],
        },
        {
            "entity_id": "light.kitchen",
            "name": "Kitchen Light",
            "state": "off",
            "area": "Kitchen",
            "aliases": [],
        },
    ]

    # Turn 1: initial prompt — must include full context
    initial = manager.build_initial_prompt(conv_id, entities, "You are HA.")
    assert "light.desk_lamp" in initial
    assert "desk lamp" in initial
    assert "office lamp" in initial

    # Turn 2: user asks something unrelated; kitchen light changes state
    entities_t2 = [
        {
            "entity_id": "light.desk_lamp",
            "name": "Desk Lamp",
            "state": "on",  # unchanged
            "area": "Office",
            "aliases": ["desk lamp", "office lamp"],
        },
        {
            "entity_id": "light.kitchen",
            "name": "Kitchen Light",
            "state": "on",  # changed
            "area": "Kitchen",
            "aliases": [],
        },
    ]
    delta_t2 = manager.build_delta_prompt(conv_id, entities_t2, "You are HA.")
    assert delta_t2 is not None
    # Entity map MUST include desk lamp even though it did not change
    assert "light.desk_lamp" in delta_t2
    assert "desk lamp" in delta_t2 or "Desk Lamp" in delta_t2
    # State change for kitchen should be reported
    assert "light.kitchen" in delta_t2

    # Turn 3: user says "turn off desk lamp" — entity map still present
    entities_t3 = entities_t2  # no further changes
    delta_t3 = manager.build_delta_prompt(conv_id, entities_t3, "You are HA.")
    assert delta_t3 is not None
    # Model MUST be able to resolve "desk lamp" to light.desk_lamp
    assert "light.desk_lamp" in delta_t3
    assert "desk lamp" in delta_t3 or "Desk Lamp" in delta_t3


@pytest.mark.anyio
async def test_delta_entity_map_excludes_state_values(manager):
    """Entity resolution map in delta must NOT include state values.

    The compact entity map is for name/alias resolution only; state is
    reported separately in the state-changes section to avoid duplication.
    """
    conv_id = "no_state_in_map_conv"
    entities = [
        {
            "entity_id": "light.living_room",
            "name": "Living Room",
            "state": "off",
            "area": "Living Room",
            "aliases": ["big light"],
        }
    ]

    manager.build_initial_prompt(conv_id, entities, "Base")
    delta = manager.build_delta_prompt(conv_id, entities, "Base")

    assert delta is not None
    # The "Entity Map" section must be present
    assert "Entity Map" in delta
    # The entity map section should not contain the bare state value 'off'
    # (it only contains entity_id;name;aliases columns)
    map_section_start = delta.index("Entity Map")
    # Find the end of the entity map section (before "State Changes" or end)
    state_changes_marker = "State Changes"
    map_section_end = (
        delta.index(state_changes_marker)
        if state_changes_marker in delta
        else len(delta)
    )
    map_section = delta[map_section_start:map_section_end]
    assert "entity_id;name;aliases" in map_section
    # The state column header "entity_id;name;state;aliases" must NOT appear in map section
    assert "entity_id;name;state;aliases" not in map_section


@pytest.mark.anyio
async def test_mcp_delta_unknown_conversation_returns_initial_prompt(manager):
    """Unknown conversation in delta path should rebuild full initial prompt."""
    delta = manager.build_delta_prompt("unknown_conv", [], "Base")
    assert "Base" in delta
    assert "Initial Full State" in delta


@pytest.mark.anyio
async def test_token_budget_initial_prompt_includes_full_state(manager):
    """Initial prompt must include entity state information for all entities."""
    entities = [
        {"entity_id": "light.a", "name": "Light A", "state": "on", "area": "Room 1"},
        {"entity_id": "switch.b", "name": "Switch B", "state": "off", "area": "Room 2"},
    ]
    prompt = manager.build_initial_prompt("budget_conv", entities, "Base")
    # All entities and their states must appear in the initial prompt
    assert "light.a" in prompt
    assert "switch.b" in prompt
    assert "on" in prompt
    assert "off" in prompt
    assert "Initial Full State" in prompt

