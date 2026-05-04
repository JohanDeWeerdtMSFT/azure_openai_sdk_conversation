"""
Entity matcher for local intent handler.

Matches user tokens to Home Assistant entities using fuzzy matching.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components import conversation
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)

from ..core.logger import AgentLogger


class EntityMatcher:
    """Matcher for finding entities based on user tokens."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: AgentLogger,
    ) -> None:
        """
        Initialize entity matcher.

        Args:
            hass: Home Assistant instance
            logger: Logger instance
        """
        self._hass = hass
        self._logger = logger

    def match_entities(self, tokens: list[str]) -> list[dict[str, Any]]:
        """
        Match tokens to exposed entities.

        Args:
            tokens: List of normalized tokens from user input

        Returns:
            List of matched entity dicts with scoring.
            Returns an empty list when the match is ambiguous (multiple entities
            share an identical alias that is fully covered by the token set), so
            callers can fall back to LLM-based disambiguation.
        """
        if not tokens:
            return []

        # Get exposed entities
        candidates = self._get_exposed_entities()

        # Score each candidate
        scored = []
        token_set = set(tokens)

        for entity in candidates:
            score = self._score_entity(entity, token_set)
            if score > 0:
                scored.append((score, entity))

        # Sort by score (descending)
        scored.sort(key=lambda x: x[0], reverse=True)

        # Return entities with top score (within 10% threshold)
        if not scored:
            return []

        top_score = scored[0][0]
        threshold = top_score * 0.9

        matched = [entity for score, entity in scored if score >= threshold]

        # Detect alias ambiguity: if two or more matched entities share an alias
        # that is fully covered by the token set, the request is ambiguous and
        # should be handled by the LLM instead of executing blindly.
        if len(matched) > 1 and self._is_alias_ambiguous(matched, token_set):
            self._logger.warning(
                "Alias ambiguity detected for tokens %s — deferring to LLM",
                tokens,
            )
            return []

        self._logger.debug(
            "Matched %d entities for tokens %s (top_score=%.1f)",
            len(matched),
            tokens,
            top_score,
        )

        return matched

    def _get_exposed_entities(self) -> list[dict[str, Any]]:
        """
        Get list of entities exposed to conversation/assist.

        Returns:
            List of entity dicts with {entity_id, name, state, area, domain, aliases}
        """
        area_reg = ar.async_get(self._hass)
        ent_reg = er.async_get(self._hass)
        dev_reg = dr.async_get(self._hass)

        entities = []

        for state in self._hass.states.async_all():
            entry = ent_reg.async_get(state.entity_id)

            # Filter: only exposed entities
            if not self._is_exposed(entry):
                continue

            # Only include light and switch domains for on/off
            domain = state.entity_id.split(".", 1)[0]
            if domain not in ("light", "switch"):
                continue

            # Get area
            area_name = ""
            area_id = None
            if entry:
                area_id = entry.area_id
                if not area_id and entry.device_id:
                    dev = dev_reg.async_get(entry.device_id)
                    if dev and dev.area_id:
                        area_id = dev.area_id

            if area_id:
                area = area_reg.async_get_area(area_id)
                if area and area.name:
                    area_name = area.name

            # Get aliases configured in Home Assistant
            aliases = self._get_aliases(entry)

            entities.append(
                {
                    "entity_id": state.entity_id,
                    "name": state.name or state.entity_id,
                    "state": state.state,
                    "area": area_name,
                    "domain": domain,
                    "aliases": aliases,
                }
            )

        return entities

    @staticmethod
    def _is_exposed(entry: er.RegistryEntry | None) -> bool:
        """Check if entity is exposed to conversation."""
        if entry is None:
            return False

        try:
            opts = entry.options or {}
            conv_opts = opts.get(conversation.DOMAIN) or opts.get("conversation") or {}
            val = conv_opts.get("should_expose", conv_opts.get("expose", None))
            return bool(val)
        except Exception:
            return False

    @staticmethod
    def _get_aliases(entry: er.RegistryEntry | None) -> list[str]:
        """Get aliases configured for entity in Home Assistant."""
        if not entry:
            return []

        try:
            opts = entry.options or {}
            conv_opts = opts.get(conversation.DOMAIN) or opts.get("conversation") or {}
            aliases = conv_opts.get("aliases", [])
            if isinstance(aliases, list):
                return [str(a) for a in aliases if a]
        except Exception:
            pass

        return []

    def _score_entity(
        self,
        entity: dict[str, Any],
        token_set: set[str],
    ) -> float:
        """
        Score an entity against token set.

        Scoring:
        - Full alias covered by token set: +5.0 per alias word
        - Token word-matches in alias: +3.5
        - Area exact match: +4.0
        - Token in name: +3.0
        - Token in entity_id: +1.5
        - Special patterns (e.g., "tavolo" → "table"): +1.0

        Alias matches are given the highest priority so that user-configured
        aliases reliably resolve to the intended entity.

        Args:
            entity: Entity dict
            token_set: Set of user tokens

        Returns:
            Score (0.0 if no match)
        """
        score = 0.0

        entity_id = entity["entity_id"].lower()
        name = entity["name"].lower()
        area = entity.get("area", "").lower()
        aliases = entity.get("aliases", [])

        for token in token_set:
            if not token:
                continue

            # Exact area match
            if token == area:
                score += 4.0

            # Token in name
            if token in name:
                score += 3.0

            # Token in entity_id
            if token in entity_id:
                score += 1.5

            # Alias word matching: check each configured alias
            for alias in aliases:
                alias_lower = alias.lower()
                alias_words = alias_lower.split()
                if token in alias_words:
                    # Token is an exact word within this alias
                    score += 3.5

            # Special patterns
            if token == "tavolo" and any(x in name for x in ["table", "desk"]):
                score += 1.0

            if token == "tv" and any(x in name for x in ["televisore", "television"]):
                score += 1.0

        # Bonus for a full alias being covered by the token set:
        # all words of the alias appear in the token set.
        for alias in aliases:
            alias_words = set(alias.lower().split())
            if alias_words and alias_words.issubset(token_set):
                score += 5.0

        return score

    @staticmethod
    def _is_alias_ambiguous(
        matched: list[dict[str, Any]],
        token_set: set[str],
    ) -> bool:
        """
        Detect alias ambiguity in the matched entity set.

        Ambiguity is defined as: two or more matched entities share an alias
        whose words are all present in the token set (i.e., the user's query
        could refer to either entity with equal confidence).

        Args:
            matched: Top-scored matched entities
            token_set: Normalized token set from user input

        Returns:
            True if the match is ambiguous, False otherwise
        """
        # Collect fully-covered aliases per entity
        alias_counts: dict[str, int] = {}
        for entity in matched:
            seen_for_entity: set[str] = set()
            for alias in entity.get("aliases", []):
                alias_lower = alias.lower()
                alias_words = set(alias_lower.split())
                if alias_words and alias_words.issubset(token_set):
                    normalized = " ".join(sorted(alias_words))
                    if normalized not in seen_for_entity:
                        seen_for_entity.add(normalized)
                        alias_counts[normalized] = alias_counts.get(normalized, 0) + 1

        return any(count >= 2 for count in alias_counts.values())
