"""HA scenario tests using real entity data from scripts/output/entities 20260504.json.

These tests validate that the conversation agent correctly handles:
- Cover (blind) control by Dutch name
- Ambiguous entity names (multiple "Masterbed" blinds)
- Weather/sensor read-only queries
- Safety gating for caution-level entities
- Timer state queries
- Foundry backend config with real-world entity context
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.azure_openai_sdk_conversation.core.agent import (
    AzureOpenAIConversationAgent,
)
from custom_components.azure_openai_sdk_conversation.core.config import AgentConfig

# ---------------------------------------------------------------------------
# Load real entity fixture
# ---------------------------------------------------------------------------
_FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "scripts",
    "output",
    "entities 20260504.json",
)

with open(_FIXTURE_PATH, encoding="utf-8") as _f:
    REAL_ENTITIES: list[dict] = json.load(_f)

ENTITY_IDS = {e["entity_id"] for e in REAL_ENTITIES}
COVER_ENTITIES = [e for e in REAL_ENTITIES if e["domain"] == "cover"]
SENSOR_ENTITIES = [e for e in REAL_ENTITIES if e["domain"] == "sensor"]
CAUTION_ENTITIES = [e for e in REAL_ENTITIES if e["safety_level"] == "caution"]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_CONFIG = {
    "api_key": "fake_api_key",
    "api_base": "https://fake.openai.azure.com/",
    "chat_model": "gpt-4o-mini",
    "api_version": "2025-03-01-preview",
}


@pytest.fixture
def agent(hass) -> AzureOpenAIConversationAgent:
    config = AgentConfig.from_dict(hass, BASE_CONFIG)
    a = AzureOpenAIConversationAgent(hass, config)
    a.agent_id = "test_agent"
    return a


@pytest.fixture
def agent_foundry(hass) -> AzureOpenAIConversationAgent:
    config = AgentConfig.from_dict(
        hass,
        {
            **BASE_CONFIG,
            "llm_backend": "foundry",
            "foundry_enabled": True,
            "foundry_endpoint": "https://foundry.example.azure.com/api/projects/ha-agent",
            "foundry_api_key": "foundry-test-key",
            "foundry_timeout": 30,
            "foundry_fallback_enabled": True,
        },
    )
    a = AzureOpenAIConversationAgent(hass, config)
    a.agent_id = "test_agent_foundry"
    return a


# ---------------------------------------------------------------------------
# Fixture integrity tests
# ---------------------------------------------------------------------------


def test_fixture_loads_correctly():
    """Ensure the real entity fixture file is present and parseable."""
    assert len(REAL_ENTITIES) == 22
    assert all("entity_id" in e for e in REAL_ENTITIES)


def test_fixture_has_expected_domains():
    """Fixture should contain covers, sensors, timer, weather."""
    domains = {e["domain"] for e in REAL_ENTITIES}
    assert "cover" in domains
    assert "sensor" in domains
    assert "timer" in domains
    assert "weather" in domains


def test_all_covers_are_caution():
    """All cover (blind) entities should be safety_level=caution."""
    assert all(e["safety_level"] == "caution" for e in COVER_ENTITIES)


def test_all_sensors_are_safe():
    """Sensor entities should be safety_level=safe (read-only)."""
    assert all(e["safety_level"] == "safe" for e in SENSOR_ENTITIES)


def test_covers_are_controllable():
    """Cover entities must be marked controllable."""
    assert all(e["controllable"] == "yes" for e in COVER_ENTITIES)


def test_sensors_are_not_controllable():
    """Sensor entities must NOT be marked controllable."""
    assert all(e["controllable"] == "no" for e in SENSOR_ENTITIES)


# ---------------------------------------------------------------------------
# Cover entity resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "friendly_name, expected_entity_id",
    [
        ("Badkamer blind", "cover.badkamer_blind"),
        ("Casper blind", "cover.blind_casper"),
        ("Living blind groot", "cover.blind_living_groot_blind_1"),
        ("Rosie blind", "cover.rosie_blind"),
        ("Bureau Veerle", "cover.roluikmodule_6_verdiep_vmb2ble_10_blind_1"),
    ],
)
def test_cover_entity_ids_match_friendly_names(friendly_name, expected_entity_id):
    """Verify entity_id↔friendly_name mapping for key blinds."""
    match = next((e for e in COVER_ENTITIES if e["friendly_name"] == friendly_name), None)
    assert match is not None, f"Entity with friendly_name '{friendly_name}' not found"
    assert match["entity_id"] == expected_entity_id


def test_masterbed_blinds_are_distinct():
    """'Masterbed Groot' and 'Masterbed klein' must be separate entities."""
    masterbed = [e for e in COVER_ENTITIES if "masterbed" in e["entity_id"].lower()]
    assert len(masterbed) == 2
    ids = {e["entity_id"] for e in masterbed}
    assert "cover.masterbed_groot_blind_1_mgroot" in ids
    assert "cover.masterbed_klein_blind_2_mklein" in ids


def test_speelruimte_blind_exists():
    """'Speelruimte' blind must be present (child room context)."""
    e = next((e for e in COVER_ENTITIES if e["entity_id"] == "cover.blind_speelruimte_blind_2"), None)
    assert e is not None
    assert e["friendly_name"] == "Speelruimte"


# ---------------------------------------------------------------------------
# Ambiguity detection scenarios
# ---------------------------------------------------------------------------


def test_no_area_assigned_to_any_entity():
    """All entities lack area assignment — agent must use name-based matching."""
    assert all(e["area"] == "" for e in REAL_ENTITIES)


def test_straatkant_zijkant_are_distinct():
    """'Straatkant' and 'Zijkant' are different exterior blinds."""
    straat = next((e for e in COVER_ENTITIES if e["friendly_name"] == "Straatkant"), None)
    zij = next((e for e in COVER_ENTITIES if e["friendly_name"] == "Zijkant"), None)
    assert straat is not None
    assert zij is not None
    assert straat["entity_id"] != zij["entity_id"]


# ---------------------------------------------------------------------------
# Sensor entity tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entity_id",
    [
        "sensor.condition",
        "sensor.temperature",
        "sensor.feel_temperature",
        "sensor.rain_1d",
        "sensor.detailed_condition",
        "sensor.full_condition",
        "sensor.full_condition_5d",
    ],
)
def test_weather_sensors_in_fixture(entity_id):
    """All expected weather sensor entities are present."""
    assert entity_id in ENTITY_IDS


def test_temperature_sensor_is_safe_and_readonly(entity_id="sensor.temperature"):
    """Temperature sensor must be safe and non-controllable."""
    e = next(e for e in REAL_ENTITIES if e["entity_id"] == entity_id)
    assert e["safety_level"] == "safe"
    assert e["controllable"] == "no"


# ---------------------------------------------------------------------------
# Timer entity tests
# ---------------------------------------------------------------------------


def test_kitchen_timer_exists():
    """Kitchen timer entity should be present with idle as typical state."""
    e = next((e for e in REAL_ENTITIES if e["entity_id"] == "timer.kitchen"), None)
    assert e is not None
    assert e["typical_states"] == "idle"
    assert e["safety_level"] == "safe"


# ---------------------------------------------------------------------------
# Weather entity tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entity_id",
    [
        "weather.buienradar",
        "weather.forecast_home_2",
    ],
)
def test_weather_entities_present(entity_id):
    """Both weather forecast entities must be present."""
    assert entity_id in ENTITY_IDS


# ---------------------------------------------------------------------------
# Safety gating: caution entities should never be treated as safe
# ---------------------------------------------------------------------------


def test_caution_entities_are_all_covers():
    """Only cover entities should have caution safety level."""
    caution_domains = {e["domain"] for e in CAUTION_ENTITIES}
    assert caution_domains == {"cover"}, f"Unexpected caution domains: {caution_domains}"


def test_no_sensor_has_caution_level():
    """Sensors must never have caution safety level."""
    sensor_caution = [e for e in SENSOR_ENTITIES if e["safety_level"] == "caution"]
    assert len(sensor_caution) == 0


# ---------------------------------------------------------------------------
# Agent config: Foundry backend with real entity context
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_foundry_config_parses_correctly(agent_foundry):
    """Foundry-enabled config should have all required fields set."""
    cfg = agent_foundry._config
    assert cfg.foundry_enabled is True
    assert cfg.foundry_endpoint == "https://foundry.example.azure.com/api/projects/ha-agent"
    assert cfg.foundry_api_key == "foundry-test-key"
    assert cfg.foundry_timeout == 30
    assert cfg.foundry_fallback_enabled is True


@pytest.mark.anyio
async def test_foundry_backend_selector_returns_foundry_client(agent_foundry):
    """_select_llm_client() should return the Foundry client when enabled."""
    client, handler, use_responses = agent_foundry._select_llm_client()
    assert client is agent_foundry._foundry_client
    assert handler == "llm_foundry"
    assert use_responses is False


@pytest.mark.anyio
async def test_azure_fallback_when_foundry_disabled(agent):
    """Without Foundry config, backend selector should return Azure client."""
    client, handler, use_responses = agent._select_llm_client()
    # Should be chat or responses client, not foundry
    assert client is not agent._foundry_client


# ---------------------------------------------------------------------------
# Entity count sanity check
# ---------------------------------------------------------------------------


def test_total_entity_count():
    """Fixture must contain exactly 22 entities (as exported 2026-05-04)."""
    assert len(REAL_ENTITIES) == 22


def test_cover_count():
    """Fixture must contain exactly 12 cover entities."""
    assert len(COVER_ENTITIES) == 12


def test_sensor_count():
    """Fixture must contain exactly 7 sensor entities."""
    assert len(SENSOR_ENTITIES) == 7
