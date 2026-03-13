"""
Text normalization with vocabulary/synonym support.

Applies regex rules and token substitutions to normalize user input.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from homeassistant.core import HomeAssistant

from ..core.config import AgentConfig
from ..core.logger import AgentLogger


class TextNormalizer:
    """Text normalizer with configurable vocabulary."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: AgentConfig,
        logger: AgentLogger,
    ) -> None:
        """
        Initialize text normalizer.

        Args:
            hass: Home Assistant instance
            config: Agent configuration
            logger: Logger instance
        """
        self._hass = hass
        self._config = config
        self._logger = logger

        # Vocabulary data
        self._token_synonyms: dict[str, str] = {}
        self._regex_rules: list[tuple[re.Pattern, str]] = []
        # Language-split vocabulary (populated by ensure_loaded)
        self._default_token_synonyms: dict[str, str] = {}
        self._default_regex_rules: list[tuple[re.Pattern, str]] = []
        self._custom_token_synonyms: dict[str, str] = {}
        self._custom_regex_rules: list[tuple[re.Pattern, str]] = []
        self._loaded = False

    async def ensure_loaded(self) -> None:
        """Load vocabulary if not already loaded."""
        if self._loaded:
            return

        # Get default vocabulary (Italian-specific)
        vocab = self._get_default_vocabulary()

        # Load custom synonyms file if configured (language-neutral)
        custom_vocab: dict[str, Any] = {}
        if self._config.synonyms_file and os.path.isfile(self._config.synonyms_file):
            try:
                custom_vocab = await self._load_synonyms_file(
                    self._config.synonyms_file
                )
                self._logger.info(
                    "Loaded custom synonyms from %s", self._config.synonyms_file
                )
            except Exception as err:
                self._logger.error(
                    "Failed to load synonyms file %s: %r",
                    self._config.synonyms_file,
                    err,
                )

        # Build default token synonyms map (Italian-specific vocabulary)
        self._default_token_synonyms: dict[str, str] = {}
        for source, target in vocab.get("token_synonyms", {}).items():
            if isinstance(source, str) and isinstance(target, str):
                self._default_token_synonyms[source.strip().lower()] = (
                    target.strip().lower()
                )

        # Compile default regex rules (Italian-specific)
        self._default_regex_rules: list[tuple[re.Pattern, str]] = []
        for rule in vocab.get("regex_rules", []):
            pattern = rule.get("pattern", "")
            replacement = rule.get("replace", "")
            if pattern and isinstance(pattern, str):
                try:
                    compiled = re.compile(pattern, flags=re.IGNORECASE)
                    self._default_regex_rules.append((compiled, replacement))
                except re.error as rex:
                    self._logger.warning(
                        "Invalid regex pattern in vocabulary: %s (error: %s)",
                        pattern,
                        rex,
                    )

        # Build custom token synonyms map (user-configured, language-neutral)
        self._custom_token_synonyms: dict[str, str] = {}
        for source, target in custom_vocab.get("token_synonyms", {}).items():
            if isinstance(source, str) and isinstance(target, str):
                self._custom_token_synonyms[source.strip().lower()] = (
                    target.strip().lower()
                )

        # Compile custom regex rules (user-configured, language-neutral)
        self._custom_regex_rules: list[tuple[re.Pattern, str]] = []
        for rule in custom_vocab.get("regex_rules", []):
            pattern = rule.get("pattern", "")
            replacement = rule.get("replace", "")
            if pattern and isinstance(pattern, str):
                try:
                    compiled = re.compile(pattern, flags=re.IGNORECASE)
                    self._custom_regex_rules.append((compiled, replacement))
                except re.error as rex:
                    self._logger.warning(
                        "Invalid regex pattern in custom vocabulary: %s (error: %s)",
                        pattern,
                        rex,
                    )

        # Legacy: keep combined view for backward compat (Italian path)
        self._token_synonyms = {
            **self._default_token_synonyms,
            **self._custom_token_synonyms,
        }
        self._regex_rules = self._default_regex_rules + self._custom_regex_rules

        self._loaded = True
        self._logger.debug(
            "Vocabulary loaded: %d default synonyms, %d custom synonyms, "
            "%d default regex rules, %d custom regex rules",
            len(self._default_token_synonyms),
            len(self._custom_token_synonyms),
            len(self._default_regex_rules),
            len(self._custom_regex_rules),
        )

    def normalize(self, text: str, language: str | None = None) -> str:
        """
        Normalize text using vocabulary rules.

        The default vocabulary contains Italian-specific substitutions (e.g.,
        ``"off" → "spegni"``).  When *language* is provided and is not Italian,
        these default substitutions are skipped to prevent cross-language token
        replacement.  User-configured custom vocabulary (``synonyms_file``) is
        always applied regardless of language.

        Args:
            text: Raw user input
            language: Optional BCP-47 language tag (e.g. ``"it"``, ``"en"``).
                When *None* the method behaves as before (applies all rules) for
                backward compatibility.

        Returns:
            Normalized text
        """
        if not text:
            return ""

        s = text.strip()

        # Determine whether the default Italian vocabulary should be applied.
        # When language is None we assume Italian for backward compatibility.
        apply_default = (language is None) or language.lower().startswith("it")

        if apply_default:
            # Apply default (Italian) regex rules first
            for pattern, replacement in self._default_regex_rules:
                s = pattern.sub(replacement, s)

            # Apply default (Italian) token synonyms
            # Process longer phrases first to avoid partial matches
            for source in sorted(
                self._default_token_synonyms.keys(), key=len, reverse=True
            ):
                target = self._default_token_synonyms[source]
                try:
                    s = re.sub(
                        rf"\b{re.escape(source)}\b",
                        target,
                        s,
                        flags=re.IGNORECASE,
                    )
                except re.error:
                    s = s.replace(source, target)

        # Always apply custom (user-configured) regex rules
        for pattern, replacement in self._custom_regex_rules:
            s = pattern.sub(replacement, s)

        # Always apply custom (user-configured) token synonyms
        for source in sorted(
            self._custom_token_synonyms.keys(), key=len, reverse=True
        ):
            target = self._custom_token_synonyms[source]
            try:
                s = re.sub(
                    rf"\b{re.escape(source)}\b",
                    target,
                    s,
                    flags=re.IGNORECASE,
                )
            except re.error:
                s = s.replace(source, target)

        # Clean up multiple spaces
        s = re.sub(r"\s{2,}", " ", s).strip()

        # Normalize to lowercase (preserving accents)
        s = s.lower()

        return s

    async def _load_synonyms_file(self, path: str) -> dict[str, Any]:
        """Load synonyms from JSON file."""

        def _read() -> dict[str, Any]:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

        return await self._hass.async_add_executor_job(_read)

    @staticmethod
    def _get_default_vocabulary() -> dict[str, Any]:
        """Get default vocabulary specification."""
        return {
            "token_synonyms": {
                # Verbs (Italian)
                "disattiva": "spegni",
                "disattivare": "spegni",
                "spegnere": "spegni",
                "spengi": "spegni",  # Common typo
                "off": "spegni",
                "attiva": "accendi",
                "attivare": "accendi",
                "accendere": "accendi",
                "on": "accendi",
                # Objects/Rooms (Italian)
                "luci": "luce",
                "lampada": "luce",
                "lampadario": "luce",
                "faretti": "luce",
                "spot": "luce",
                "salotto": "soggiorno",
                "sala": "soggiorno",
                "bagni": "bagno",
                # Common collocations
                "luce tavolo": "tavolo",
                "luci tavolo": "tavolo",
                "tavolo cucina": "tavolo",
                "luce cucina": "cucina",
                "luci cucina": "cucina",
            },
            "regex_rules": [
                # Remove articles before verbs
                {
                    "pattern": r"\b(spegni|accendi)\s+(il|lo|la|i|gli|le|l')\s+",
                    "replace": r"\1 ",
                },
                # Simplify "luce del tavolo" ? "tavolo"
                {
                    "pattern": r"\b(luce|luci)\s+(del|della|dello|dei|degli|delle)\s+(tavolo)\b",
                    "replace": r"\3",
                },
                # Simplify "luce tavolo" ? "tavolo"
                {
                    "pattern": r"\b(luce|luci)\s+tavolo\b",
                    "replace": "tavolo",
                },
                # Simplify "tavolo cucina" ? "tavolo"
                {
                    "pattern": r"\btavolo\s+cucina\b",
                    "replace": "tavolo",
                },
                # Collapse multiple spaces
                {
                    "pattern": r"\s{2,}",
                    "replace": " ",
                },
            ],
        }

    @staticmethod
    def _merge_vocabularies(
        base: dict[str, Any],
        custom: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Merge two vocabulary specifications.

        Custom rules are added to base rules (not replaced).
        """
        merged = {
            "token_synonyms": dict(base.get("token_synonyms", {})),
            "regex_rules": list(base.get("regex_rules", [])),
        }

        # Merge token synonyms (custom overrides base)
        custom_synonyms = custom.get("token_synonyms", {})
        if isinstance(custom_synonyms, dict):
            merged["token_synonyms"].update(custom_synonyms)

        # Append regex rules
        custom_rules = custom.get("regex_rules", [])
        if isinstance(custom_rules, list):
            merged["regex_rules"].extend(custom_rules)

        return merged

    async def close(self) -> None:
        """Clean up resources."""
        pass
