"""
System prompt builder with MCP integration.

Builds system prompts with entity state information, using either:
- Full context (first message)
- Delta updates (MCP mode for subsequent messages)
"""

from __future__ import annotations

from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template as HATemplate

from ..core.config import AgentConfig
from ..core.logger import AgentLogger
from .entity_collector import EntityCollector
from .mcp_manager import MCPManager


class SystemPromptBuilder:
    """Builder for system prompts with entity context."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: AgentConfig,
        logger: AgentLogger,
    ) -> None:
        """
        Initialize system prompt builder.

        Args:
            hass: Home Assistant instance
            config: Agent configuration
            logger: Logger instance
        """
        self._hass = hass
        self._config = config
        self._logger = logger

        # Entity collector
        self._collector = EntityCollector(hass, config, logger)

        # MCP manager (optional)
        self._mcp: Optional[MCPManager] = None
        if config.mcp_enabled:
            self._mcp = MCPManager(
                hass=hass,
                ttl_seconds=config.mcp_ttl_seconds,
                logger=logger,
            )
            hass.loop.create_task(self._mcp.start())

    async def build(
        self,
        conversation_id: Optional[str] = None,
    ) -> str:
        """
        Build system prompt for current request.

        Args:
            conversation_id: Optional conversation ID for MCP delta

        Returns:
            System prompt string
        """
        # Get base prompt template
        base_prompt = self._config.system_prompt

        # Get entity context
        entities = await self._collector.collect()

        # Use MCP if enabled and conversation_id present
        if self._mcp and conversation_id:
            is_initial = self._mcp.is_new_conversation(conversation_id)

            if is_initial:
                # First message: full context including all entity states
                prompt = self._mcp.build_initial_prompt(
                    conversation_id=conversation_id,
                    entities=entities,
                    base_prompt=base_prompt,
                )
                self._logger.debug(
                    "Built initial system prompt with %d entities", len(entities)
                )
            else:
                # Subsequent message: entity resolution map + state delta.
                # build_delta_prompt always returns a non-None string so the model
                # retains the full entity map (name/alias → entity_id) every turn.
                prompt = self._mcp.build_delta_prompt(
                    conversation_id=conversation_id,
                    entities=entities,
                )
                if not prompt:
                    # Conversation was not found in MCP state (e.g. TTL expired);
                    # fall back to full context so entity resolution is never lost.
                    self._logger.warning(
                        "MCP delta returned None for conv=%s; falling back to full context",
                        conversation_id,
                    )
                    prompt = await self._build_full_prompt(base_prompt, entities)
                else:
                    self._logger.debug("Built delta system prompt for conv=%s", conversation_id)

            return prompt

        # No MCP: build full context every time
        prompt = await self._build_full_prompt(base_prompt, entities)
        return prompt

    async def _build_full_prompt(
        self,
        base_prompt: str,
        entities: list[dict],
    ) -> str:
        """
        Build full system prompt with entity context.

        Args:
            base_prompt: Base prompt template
            entities: List of entity dicts

        Returns:
            Formatted system prompt
        """
        # Try to render with Jinja2 template
        try:
            template = HATemplate(base_prompt, hass=self._hass)
            rendered = template.async_render(
                {
                    "exposed_entities": entities,
                }
            )
        except Exception as err:
            self._logger.debug("Template rendering failed, using base prompt: %s", err)
            rendered = base_prompt

        # Append entity context if not already included
        if "exposed_entities" not in base_prompt.lower():
            entity_context = self._format_entity_context(entities)
            rendered = f"{rendered}\n\n{entity_context}"

        return rendered

    @staticmethod
    def _format_entity_context(entities: list[dict]) -> str:
        """
        Format entity context as CSV grouped by area.

        Args:
            entities: List of entity dicts

        Returns:
            Formatted entity context string
        """
        if not entities:
            return "No exposed entities available."

        # Group by area
        by_area: dict[str, list[dict]] = {}
        for entity in entities:
            area = entity.get("area") or "_no_area"
            if area not in by_area:
                by_area[area] = []
            by_area[area].append(entity)

        # Build formatted string
        lines = [
            "**Entity Resolution Rules** (STRICT - follow before every tool call):",
            "1. Always look up the entity list below to find the exact `entity_id`.",
            "2. Match the user's name or alias (e.g., 'desk lamp', 'the lamp') to the"
            " `name` or `aliases` columns.",
            "3. NEVER guess, invent, or hallucinate entity_ids.",
            "4. Do NOT call any service tool until you have resolved the exact"
            " entity_id from the list below.",
            "5. If no matching entity is found, ask the user for clarification instead"
            " of making a tool call.",
            "",
            "**Entity State Information**:",
        ]

        for area in sorted(by_area.keys()):
            if area == "_no_area":
                lines.append("\nEntities without configured area:")
            else:
                lines.append(f"\nEntities in: {area}")

            lines.append("```csv")
            lines.append("entity_id;name;state;aliases")

            for entity in sorted(by_area[area], key=lambda e: e["entity_id"]):
                aliases = "/".join(entity.get("aliases", []))
                lines.append(
                    f"{entity['entity_id']};{entity['name']};{entity['state']};{aliases}"
                )

            lines.append("```")

        return "\n".join(lines)

    async def close(self) -> None:
        """Clean up resources."""
        if self._mcp:
            await self._mcp.stop()
