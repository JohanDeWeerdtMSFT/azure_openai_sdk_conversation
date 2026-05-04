"""Tests for EntityMatcher alias resolution reliability.

Covers:
- Direct name matching
- Alias matching (single-word and multi-word aliases)
- Area + alias narrowing to disambiguate
- Conflicting alias scenario (ambiguity → empty result)
"""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.azure_openai_sdk_conversation.core.config import AgentConfig
from custom_components.azure_openai_sdk_conversation.core.logger import AgentLogger
from custom_components.azure_openai_sdk_conversation.local_intent.entity_matcher import (
    EntityMatcher,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    entity_id: str,
    area_id: str | None = None,
    device_id: str | None = None,
    exposed: bool = True,
    aliases: list[str] | None = None,
) -> MagicMock:
    """Create a mock entity registry entry."""
    entry = MagicMock()
    entry.area_id = area_id
    entry.device_id = device_id
    conv_opts: dict = {"should_expose": exposed}
    if aliases is not None:
        conv_opts["aliases"] = aliases
    entry.options = {"conversation": conv_opts}
    return entry


def _make_state(entity_id: str, name: str, state: str = "off") -> MagicMock:
    """Create a mock HA state object."""
    s = MagicMock()
    s.entity_id = entity_id
    s.name = name
    s.state = state
    return s


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
def matcher(hass, logger):
    return EntityMatcher(hass, logger)


# ---------------------------------------------------------------------------
# Test: direct name match
# ---------------------------------------------------------------------------

def test_direct_name_match(matcher, hass):
    """Token that appears in the entity name resolves to the correct entity."""
    state = _make_state("light.kitchen", "Kitchen Light")
    entry = _make_entry("light.kitchen")

    mock_ent_reg = MagicMock()
    mock_ent_reg.async_get.return_value = entry
    mock_dev_reg = MagicMock()
    mock_area_reg = MagicMock()
    mock_area_reg.async_get_area.return_value = None

    hass.states.async_all.return_value = [state]

    with (
        patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_ent_reg),
        patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dev_reg),
        patch("homeassistant.helpers.area_registry.async_get", return_value=mock_area_reg),
    ):
        results = matcher.match_entities(["kitchen"])

    assert len(results) == 1
    assert results[0]["entity_id"] == "light.kitchen"


# ---------------------------------------------------------------------------
# Test: single-word alias match
# ---------------------------------------------------------------------------

def test_single_word_alias_match(matcher, hass):
    """A single-word alias resolves reliably to the configured entity."""
    # Entity whose name does not contain the alias word, but its alias does.
    state = _make_state("light.office_1", "Office Overhead")
    entry = _make_entry("light.office_1", aliases=["lamp"])

    unrelated_state = _make_state("switch.tv", "TV Switch")
    unrelated_entry = _make_entry("switch.tv")

    mock_ent_reg = MagicMock()
    mock_ent_reg.async_get.side_effect = lambda eid: (
        entry if eid == "light.office_1" else unrelated_entry
    )
    mock_dev_reg = MagicMock()
    mock_area_reg = MagicMock()
    mock_area_reg.async_get_area.return_value = None

    hass.states.async_all.return_value = [state, unrelated_state]

    with (
        patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_ent_reg),
        patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dev_reg),
        patch("homeassistant.helpers.area_registry.async_get", return_value=mock_area_reg),
    ):
        results = matcher.match_entities(["lamp"])

    assert len(results) == 1
    assert results[0]["entity_id"] == "light.office_1"


# ---------------------------------------------------------------------------
# Test: multi-word alias match
# ---------------------------------------------------------------------------

def test_multi_word_alias_match(matcher, hass):
    """A multi-word alias ('desk lamp') resolves to the correct entity."""
    state = _make_state("light.desk", "Work Light")
    entry = _make_entry("light.desk", aliases=["desk lamp"])

    other_state = _make_state("light.ceiling", "Ceiling Light")
    other_entry = _make_entry("light.ceiling")

    mock_ent_reg = MagicMock()
    mock_ent_reg.async_get.side_effect = lambda eid: (
        entry if eid == "light.desk" else other_entry
    )
    mock_dev_reg = MagicMock()
    mock_area_reg = MagicMock()
    mock_area_reg.async_get_area.return_value = None

    hass.states.async_all.return_value = [state, other_state]

    with (
        patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_ent_reg),
        patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dev_reg),
        patch("homeassistant.helpers.area_registry.async_get", return_value=mock_area_reg),
    ):
        results = matcher.match_entities(["desk", "lamp"])

    assert len(results) == 1
    assert results[0]["entity_id"] == "light.desk"


# ---------------------------------------------------------------------------
# Test: area + alias narrows to single entity
# ---------------------------------------------------------------------------

def test_area_plus_alias_narrows_to_one(matcher, hass):
    """Area token + alias token together resolve to a single entity."""
    # Two entities both have the alias "lamp", but only one is in "bedroom".
    bedroom_state = _make_state("light.bedroom_lamp", "Bedroom Lamp")
    bedroom_entry = _make_entry("light.bedroom_lamp", area_id="area_bedroom", aliases=["lamp"])

    office_state = _make_state("light.office_lamp", "Office Lamp")
    office_entry = _make_entry("light.office_lamp", area_id="area_office", aliases=["lamp"])

    mock_ent_reg = MagicMock()
    mock_ent_reg.async_get.side_effect = lambda eid: (
        bedroom_entry if eid == "light.bedroom_lamp" else office_entry
    )
    mock_dev_reg = MagicMock()
    mock_area_reg = MagicMock()

    def _get_area(area_id):
        area = MagicMock()
        area.name = "bedroom" if area_id == "area_bedroom" else "office"
        return area

    mock_area_reg.async_get_area.side_effect = _get_area

    hass.states.async_all.return_value = [bedroom_state, office_state]

    with (
        patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_ent_reg),
        patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dev_reg),
        patch("homeassistant.helpers.area_registry.async_get", return_value=mock_area_reg),
    ):
        # "bedroom" area token + "lamp" alias token → only bedroom lamp
        results = matcher.match_entities(["bedroom", "lamp"])

    assert len(results) == 1
    assert results[0]["entity_id"] == "light.bedroom_lamp"


# ---------------------------------------------------------------------------
# Test: conflicting alias → ambiguity → empty result
# ---------------------------------------------------------------------------

def test_conflicting_alias_returns_empty(matcher, hass):
    """Two entities sharing the same alias produce an empty result (ambiguous)."""
    state_a = _make_state("light.entity_a", "Entity A")
    entry_a = _make_entry("light.entity_a", aliases=["lamp"])

    state_b = _make_state("light.entity_b", "Entity B")
    entry_b = _make_entry("light.entity_b", aliases=["lamp"])

    mock_ent_reg = MagicMock()
    mock_ent_reg.async_get.side_effect = lambda eid: (
        entry_a if eid == "light.entity_a" else entry_b
    )
    mock_dev_reg = MagicMock()
    mock_area_reg = MagicMock()
    mock_area_reg.async_get_area.return_value = None

    hass.states.async_all.return_value = [state_a, state_b]

    with (
        patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_ent_reg),
        patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dev_reg),
        patch("homeassistant.helpers.area_registry.async_get", return_value=mock_area_reg),
    ):
        results = matcher.match_entities(["lamp"])

    # Ambiguous: both entities expose alias "lamp" → must defer to LLM
    assert results == []


# ---------------------------------------------------------------------------
# Test: conflicting multi-word alias → ambiguity → empty result
# ---------------------------------------------------------------------------

def test_conflicting_multiword_alias_returns_empty(matcher, hass):
    """Two entities with identical multi-word aliases trigger ambiguity handling."""
    state_a = _make_state("light.entity_a", "Entity A")
    entry_a = _make_entry("light.entity_a", aliases=["desk lamp"])

    state_b = _make_state("light.entity_b", "Entity B")
    entry_b = _make_entry("light.entity_b", aliases=["desk lamp"])

    mock_ent_reg = MagicMock()
    mock_ent_reg.async_get.side_effect = lambda eid: (
        entry_a if eid == "light.entity_a" else entry_b
    )
    mock_dev_reg = MagicMock()
    mock_area_reg = MagicMock()
    mock_area_reg.async_get_area.return_value = None

    hass.states.async_all.return_value = [state_a, state_b]

    with (
        patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_ent_reg),
        patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dev_reg),
        patch("homeassistant.helpers.area_registry.async_get", return_value=mock_area_reg),
    ):
        results = matcher.match_entities(["desk", "lamp"])

    assert results == []


# ---------------------------------------------------------------------------
# Test: alias beats name match (scoring priority)
# ---------------------------------------------------------------------------

def test_alias_scores_higher_than_name(matcher, hass):
    """Entity with an exact alias match outscores an entity whose name merely
    contains the query token."""
    # Entity A: name contains "lamp" but no explicit alias
    state_a = _make_state("light.floor_lamp", "Floor Lamp")
    entry_a = _make_entry("light.floor_lamp")

    # Entity B: name is generic, but has alias "desk lamp"
    state_b = _make_state("light.desk_light", "Desk Light")
    entry_b = _make_entry("light.desk_light", aliases=["desk lamp"])

    mock_ent_reg = MagicMock()
    mock_ent_reg.async_get.side_effect = lambda eid: (
        entry_a if eid == "light.floor_lamp" else entry_b
    )
    mock_dev_reg = MagicMock()
    mock_area_reg = MagicMock()
    mock_area_reg.async_get_area.return_value = None

    hass.states.async_all.return_value = [state_a, state_b]

    with (
        patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_ent_reg),
        patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dev_reg),
        patch("homeassistant.helpers.area_registry.async_get", return_value=mock_area_reg),
    ):
        # Tokens "desk lamp" → entity B should win (alias exact match bonus)
        results = matcher.match_entities(["desk", "lamp"])

    assert len(results) == 1
    assert results[0]["entity_id"] == "light.desk_light"


# ---------------------------------------------------------------------------
# Test: entity with no aliases still works via name
# ---------------------------------------------------------------------------

def test_no_aliases_name_fallback(matcher, hass):
    """Entities without configured aliases still resolve via name matching."""
    state = _make_state("light.hallway", "Hallway Light")
    entry = _make_entry("light.hallway", aliases=[])

    mock_ent_reg = MagicMock()
    mock_ent_reg.async_get.return_value = entry
    mock_dev_reg = MagicMock()
    mock_area_reg = MagicMock()
    mock_area_reg.async_get_area.return_value = None

    hass.states.async_all.return_value = [state]

    with (
        patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_ent_reg),
        patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dev_reg),
        patch("homeassistant.helpers.area_registry.async_get", return_value=mock_area_reg),
    ):
        results = matcher.match_entities(["hallway"])

    assert len(results) == 1
    assert results[0]["entity_id"] == "light.hallway"


# ---------------------------------------------------------------------------
# Unit tests for static helpers
# ---------------------------------------------------------------------------

def test_is_alias_ambiguous_true():
    """_is_alias_ambiguous returns True when two entities share a covered alias."""
    entities = [
        {"aliases": ["lamp"]},
        {"aliases": ["lamp"]},
    ]
    assert EntityMatcher._is_alias_ambiguous(entities, {"lamp"}) is True


def test_is_alias_ambiguous_false_different_aliases():
    """_is_alias_ambiguous returns False when aliases are distinct."""
    entities = [
        {"aliases": ["desk lamp"]},
        {"aliases": ["floor lamp"]},
    ]
    assert EntityMatcher._is_alias_ambiguous(entities, {"desk", "lamp"}) is False


def test_is_alias_ambiguous_false_uncovered_alias():
    """_is_alias_ambiguous returns False when the alias is not covered by tokens."""
    entities = [
        {"aliases": ["desk lamp"]},
        {"aliases": ["desk lamp"]},
    ]
    # Only one of the two alias words is in token_set → alias not fully covered
    assert EntityMatcher._is_alias_ambiguous(entities, {"desk"}) is False


def test_get_aliases_none_entry():
    """_get_aliases returns empty list when entry is None."""
    assert EntityMatcher._get_aliases(None) == []


def test_get_aliases_no_options():
    """_get_aliases returns empty list when no options are present."""
    entry = MagicMock()
    entry.options = {}
    assert EntityMatcher._get_aliases(entry) == []


def test_get_aliases_with_aliases():
    """_get_aliases correctly extracts aliases from entity options."""
    entry = MagicMock()
    entry.options = {"conversation": {"should_expose": True, "aliases": ["desk lamp", "work light"]}}
    result = EntityMatcher._get_aliases(entry)
    assert result == ["desk lamp", "work light"]
