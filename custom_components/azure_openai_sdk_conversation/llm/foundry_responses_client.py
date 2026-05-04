"""
Foundry Published Agent Responses API client for Home Assistant.

This module provides a wrapper around the Published Agent Application Responses
endpoint, with automatic multi-turn context replay (stateless endpoint pattern).

Key features:
- httpx-based (pure Python, ARM-friendly, no C++ dependencies)
- API key or Entra bearer token authentication
- Automatic multi-turn history replay
- SSE streaming support (future enhancement)
- Response parsing and token counting
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx
from homeassistant.core import HomeAssistant
from homeassistant.helpers.httpx_client import get_async_client

from ..core.config import AgentConfig
from ..core.logger import AgentLogger


class FoundryResponsesClient:
    """Client for Foundry Published Agent Responses API."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: AgentConfig,
        logger: AgentLogger,
    ) -> None:
        """
        Initialize Foundry Responses client.

        Args:
            hass: Home Assistant instance
            config: Agent configuration (must include foundry_endpoint, foundry_api_key)
            logger: Logger instance
        """
        self._hass = hass
        self._config = config
        self._logger = logger
        self._http = get_async_client(hass)

        # Endpoint and auth
        self._endpoint = (config.foundry_endpoint or "").rstrip("/")
        self._api_key = config.foundry_api_key
        self._timeout = config.api_timeout or 30

        if not self._endpoint:
            raise ValueError(
                "foundry_endpoint must be configured for Foundry Responses client"
            )

        self._logger.debug(
            "FoundryResponsesClient initialized: endpoint=%s (last 30 chars)",
            self._endpoint[-30:] if self._endpoint else "N/A",
        )

    async def _get_headers(self) -> dict[str, str]:
        """
        Build request headers.

        Supports both API key and Entra bearer token authentication.
        If API key is configured, use it; otherwise fall back to Entra token.
        """
        headers = {"Content-Type": "application/json"}

        if self._api_key:
            headers["api-key"] = self._api_key
        else:
            # Future: Support Entra bearer token via Azure CLI credential
            # For now, require API key for Home Assistant container compatibility
            raise ValueError(
                "API key is required for Foundry Responses client. "
                "Set foundry_api_key in config."
            )

        return headers

    async def complete(
        self,
        messages: list[dict[str, str]],
        conversation_id: Optional[str] = None,
        user_message: str = "",
        track_callback: Optional[callable] = None,
    ) -> tuple[str, dict[str, int]]:
        """
        Request completion from the Foundry agent (no tools).

        Args:
            messages: Conversation history (will be replayed automatically)
            conversation_id: Optional conversation ID for logging
            user_message: User's message for logging
            track_callback: Optional callback to track response chunks

        Returns:
            Tuple of (response_text, usage_dict)
        """
        # Build payload with full conversation history
        # Published Responses API is stateless - replay full history
        payload = {"input": messages}

        await self._logger.log_request(
            api="Foundry Responses",
            payload=payload,
            user_message=user_message,
            conversation_id=conversation_id,
        )

        return await self._call_endpoint(
            payload=payload,
            conversation_id=conversation_id,
            track_callback=track_callback,
        )

    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        conversation_id: Optional[str] = None,
        user_message: str = "",
        track_callback: Optional[callable] = None,
    ) -> tuple[dict[str, Any], dict[str, int]]:
        """
        Request completion with tool calling (if supported by agent).

        Note: Published agents may not support tool calling via direct API;
        tools are typically defined within the agent definition itself.

        Args:
            messages: Conversation history
            tools: Tool definitions (may be ignored by published agent)
            conversation_id: Optional conversation ID for logging
            user_message: User's message for logging
            track_callback: Optional callback to track response chunks

        Returns:
            Tuple of (response_dict, usage_dict)
        """
        # Published agents don't typically accept tools via API
        # but pass them through for future extensibility
        payload = {
            "input": messages,
            # tools field is optional; published agents may ignore it
            # "tools": tools,
        }

        await self._logger.log_request(
            api="Foundry Responses (with tools)",
            payload=payload,
            user_message=user_message,
            conversation_id=conversation_id,
        )

        return await self._call_endpoint(
            payload=payload,
            conversation_id=conversation_id,
            track_callback=track_callback,
            with_tools=True,
        )

    async def _call_endpoint(
        self,
        payload: dict[str, Any],
        conversation_id: Optional[str] = None,
        track_callback: Optional[callable] = None,
        with_tools: bool = False,
    ) -> tuple[Any, dict[str, int]]:
        """
        Call the Foundry Responses endpoint and handle response.

        Args:
            payload: Request payload
            conversation_id: Optional conversation ID
            track_callback: Optional callback for tracking
            with_tools: Whether this is a tool-calling request

        Returns:
            Tuple of (output, usage_dict)

        Raises:
            httpx.HTTPError: If request fails
            ValueError: If response is malformed
        """
        headers = await self._get_headers()

        try:
            async with self._http.stream(
                "POST",
                self._endpoint,
                json=payload,
                headers=headers,
                timeout=self._timeout,
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise httpx.HTTPError(
                        f"HTTP {response.status_code}: {error_text.decode('utf-8', errors='ignore')}"
                    )

                # Read full response body for JSON parsing
                # (streaming support can be added later)
                data = await response.aread()
                import json

                response_data = json.loads(data)

                # Extract output and usage
                output = self._extract_output_text(response_data)
                usage = self._extract_usage(response_data)

                # Prepare response dict for tools case
                if with_tools:
                    response_dict = {"output": output, "usage": usage}
                    return response_dict, usage
                else:
                    return output, usage

        except Exception as err:
            self._logger.error(
                "Foundry Responses call failed: %s",
                str(err),
                exc_info=True,
            )
            raise

    @staticmethod
    def _extract_output_text(response: dict[str, Any]) -> str:
        """
        Extract output text from Foundry Responses API response.

        Handles variable response schemas:
        - {"output_text": "..."}
        - {"output": [{"type": "message", "content": [{"type": "text", "text": "..."}]}]}
        """
        # Direct output_text field
        if isinstance(response.get("output_text"), str):
            return response["output_text"]

        # Nested output array with content
        for item in response.get("output") or []:
            if item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if content.get("type") in ("output_text", "text"):
                    text_value = content.get("text")
                    if isinstance(text_value, str):
                        return text_value

        return ""

    @staticmethod
    def _extract_usage(response: dict[str, Any]) -> dict[str, int]:
        """
        Extract token usage from Foundry Responses API response.

        Returns dict with prompt_tokens, completion_tokens, total_tokens.
        """
        usage = response.get("usage") or {}
        return {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

    def close(self) -> None:
        """Close the client (cleanup if needed)."""
        self._logger.debug("FoundryResponsesClient closed")
