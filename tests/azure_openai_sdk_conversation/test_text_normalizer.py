"""Tests for language-aware text normalization."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.azure_openai_sdk_conversation.core.config import AgentConfig
from custom_components.azure_openai_sdk_conversation.core.logger import AgentLogger
from custom_components.azure_openai_sdk_conversation.local_intent.local_handler import (
    LocalIntentHandler,
)
from custom_components.azure_openai_sdk_conversation.local_intent.text_normalizer import (
    TextNormalizer,
)


@pytest.fixture
def mock_config(hass):
    return AgentConfig.from_dict(
        hass,
        {
            "api_key": "test",
            "api_base": "https://test",
            "chat_model": "gpt-4o",
            "vocabulary_enable": True,
        },
    )


@pytest.fixture
def logger(hass, mock_config):
    return AgentLogger(hass, mock_config)


@pytest.fixture
def normalizer(hass, mock_config, logger):
    return TextNormalizer(hass, mock_config, logger)


@pytest.fixture
def handler(hass, mock_config, logger):
    return LocalIntentHandler(hass, mock_config, logger)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _loaded(normalizer: TextNormalizer) -> TextNormalizer:
    """Ensure vocabulary is loaded before running assertions."""
    await normalizer.ensure_loaded()
    return normalizer


# ---------------------------------------------------------------------------
# Italian path – default vocabulary MUST be applied
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_italian_off_is_normalized(normalizer):
    """Italian synonym 'off' → 'spegni' is applied for language='it'."""
    n = await _loaded(normalizer)
    result = n.normalize("off la luce", language="it")
    assert "spegni" in result, f"Expected 'spegni' in '{result}'"
    assert "off" not in result


@pytest.mark.anyio
async def test_italian_on_is_normalized(normalizer):
    """Italian synonym 'on' → 'accendi' is applied for language='it'."""
    n = await _loaded(normalizer)
    result = n.normalize("on la luce", language="it")
    assert "accendi" in result
    assert "on" not in result


@pytest.mark.anyio
async def test_italian_verb_forms_normalized(normalizer):
    """Italian verb forms are normalised for language='it'."""
    n = await _loaded(normalizer)
    for src in ("disattiva", "spegnere", "spengi"):
        result = n.normalize(f"{src} la luce", language="it")
        assert "spegni" in result, f"Expected 'spegni' for input starting with '{src}'"


@pytest.mark.anyio
async def test_italian_locale_tag(normalizer):
    """Full locale tag like 'it-IT' is treated as Italian."""
    n = await _loaded(normalizer)
    result = n.normalize("off luce soggiorno", language="it-IT")
    assert "spegni" in result


@pytest.mark.anyio
async def test_italian_no_language_backward_compat(normalizer):
    """When language is None the default Italian vocabulary is still applied (backward compat)."""
    n = await _loaded(normalizer)
    result = n.normalize("off la luce", language=None)
    assert "spegni" in result


# ---------------------------------------------------------------------------
# English path – default Italian vocabulary MUST NOT be applied
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_english_off_not_replaced(normalizer):
    """English 'off' must NOT be replaced with Italian 'spegni' for language='en'."""
    n = await _loaded(normalizer)
    result = n.normalize("can you turn off the desk lamp please", language="en")
    assert "spegni" not in result, f"Unexpected 'spegni' in '{result}'"
    assert "off" in result


@pytest.mark.anyio
async def test_english_on_not_replaced(normalizer):
    """English 'on' must NOT be replaced with Italian 'accendi' for language='en'."""
    n = await _loaded(normalizer)
    result = n.normalize("please turn on the kitchen light", language="en")
    assert "accendi" not in result
    assert "on" in result


@pytest.mark.anyio
async def test_english_locale_tag(normalizer):
    """Full locale tag like 'en-US' is treated as English."""
    n = await _loaded(normalizer)
    result = n.normalize("turn off the light", language="en-US")
    assert "spegni" not in result


@pytest.mark.anyio
async def test_non_italian_language_not_transformed(normalizer):
    """Non-Italian language (e.g. 'fr') also skips Italian vocab."""
    n = await _loaded(normalizer)
    result = n.normalize("éteindre off la lampe", language="fr")
    assert "spegni" not in result


# ---------------------------------------------------------------------------
# Mixed-language edge cases
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_repro_case_from_issue(normalizer):
    """Exact repro from the issue: 'off' in English sentence must not become 'spegni'."""
    n = await _loaded(normalizer)
    result = n.normalize("can you turn off the desk lamp please", language="en")
    assert "spegni" not in result
    # The word 'off' should still be present
    assert "off" in result


@pytest.mark.anyio
async def test_italian_text_spot_normalized(normalizer):
    """Italian object synonym 'spot' → 'luce' applied for Italian."""
    n = await _loaded(normalizer)
    result = n.normalize("accendi gli spot", language="it")
    assert "luce" in result


@pytest.mark.anyio
async def test_english_word_spot_not_normalized(normalizer):
    """English input with 'spot' must NOT be replaced with 'luce'."""
    n = await _loaded(normalizer)
    result = n.normalize("turn on the spot light", language="en")
    assert "luce" not in result


# ---------------------------------------------------------------------------
# LocalIntentHandler.normalize_text – language forwarding
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handler_normalize_text_english(handler):
    """LocalIntentHandler.normalize_text passes language and skips Italian vocab."""
    await handler.ensure_vocabulary_loaded()
    result = handler.normalize_text("can you turn off the desk lamp", language="en")
    assert "spegni" not in result
    assert "off" in result


@pytest.mark.anyio
async def test_handler_normalize_text_italian(handler):
    """LocalIntentHandler.normalize_text passes language and applies Italian vocab."""
    await handler.ensure_vocabulary_loaded()
    result = handler.normalize_text("off la luce", language="it")
    assert "spegni" in result


@pytest.mark.anyio
async def test_handler_normalize_text_no_language(handler):
    """LocalIntentHandler.normalize_text without language still applies Italian vocab (backward compat)."""
    await handler.ensure_vocabulary_loaded()
    result = handler.normalize_text("off la luce")
    assert "spegni" in result
