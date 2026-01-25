import json
import logging
import os
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_VERSION = "v1beta"
OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_PROVIDER = "openrouter"


class GoogleAIError(Exception):
    """Base error for Google AI client failures."""


class GoogleAIRateLimitError(GoogleAIError):
    """Raised when the API responds with a rate-limit status."""


class GoogleAIRequestError(GoogleAIError):
    """Raised for request/transport/HTTP errors."""


class GoogleAIParseError(GoogleAIError):
    """Raised when parsing the API response fails."""


def _resolve_base_url(configured: str | None) -> str:
    if not configured:
        return DEFAULT_BASE_URL

    parsed = urlparse(configured)
    if not parsed.scheme or not parsed.netloc:
        return DEFAULT_BASE_URL

    base = f"{parsed.scheme}://{parsed.netloc}"
    path_parts = [part for part in parsed.path.split("/") if part]
    version = None
    if path_parts and path_parts[0].startswith("v1"):
        version = path_parts[0]
    if not version:
        version = DEFAULT_VERSION
    return f"{base}/{version}"


class GoogleAIClient:
    provider = "google"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self._api_key = api_key or os.getenv("GOOGLE_AI_API_KEY")
        if not self._api_key:
            raise ValueError("GOOGLE_AI_API_KEY environment variable is not set")

        configured_base = (
            base_url or os.getenv("GEMINI_API_BASE_URL") or os.getenv("GEMINI_API_URL")
        )
        self._base_url = _resolve_base_url(configured_base)

    @property
    def base_url(self) -> str:
        return self._base_url

    def build_generate_content_url(self, model: str) -> str:
        model = (model or "").strip()
        if not model:
            raise ValueError("model is required")
        return f"{self._base_url}/models/{model}:generateContent"

    def build_models_url(self) -> str:
        return f"{self._base_url}/models"

    async def generate_content(
        self,
        model: str,
        payload: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        url = self.build_generate_content_url(model)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    url,
                    params={"key": self._api_key},
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise GoogleAIRequestError("Request timed out") from exc
        except httpx.RequestError as exc:
            logger.error("Google AI request failed: %s", exc)
            raise GoogleAIRequestError(f"Request failed: {exc}") from exc

        if response.status_code == 429:
            raise GoogleAIRateLimitError("Rate limit exceeded. Please try again later.")
        if response.status_code != 200:
            raise GoogleAIRequestError(
                f"API request failed with status {response.status_code}: {response.text}"
            )

        return response.json()

    async def check_health(self, timeout: float = 10.0) -> tuple[bool, str | None]:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    self.build_models_url(),
                    params={"key": self._api_key, "pageSize": 1},
                )
        except Exception as exc:
            logger.error("Google AI health check error: %s", exc, exc_info=True)
            return False, str(exc)[:200]

        if response.status_code == 200:
            return True, None

        preview = response.text[:200] if response.text else ""
        logger.warning("Google AI health check failed: %s %s", response.status_code, preview)
        return False, f"status_{response.status_code}: {preview}"


def _resolve_openrouter_base_url(configured: str | None) -> str:
    if not configured:
        return OPENROUTER_DEFAULT_BASE_URL

    parsed = urlparse(configured)
    if not parsed.scheme or not parsed.netloc:
        return OPENROUTER_DEFAULT_BASE_URL

    base = f"{parsed.scheme}://{parsed.netloc}"
    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts:
        base = f"{base}/{'/'.join(path_parts)}"
    return base.rstrip("/")


def _normalize_provider(value: str | None) -> str:
    if not value:
        return DEFAULT_PROVIDER
    lowered = value.strip().lower()
    if lowered in {"google", "googleai", "gemini"}:
        return "google"
    if lowered in {"openrouter", "open_router", "router"}:
        return "openrouter"
    logger.warning("Unknown AI provider '%s', defaulting to google.", value)
    return DEFAULT_PROVIDER


OPENROUTER_DEFAULT_VISION_MODEL = "google/gemini-2.0-flash-001"


class OpenRouterAIClient:
    provider = "openrouter"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self._api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self._api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is not set")

        configured_base = (
            base_url or os.getenv("OPENROUTER_API_BASE_URL") or os.getenv("OPENROUTER_API_URL")
        )
        self._base_url = _resolve_openrouter_base_url(configured_base)
        self._site_url = os.getenv("OPENROUTER_SITE_URL") or os.getenv("OPENROUTER_HTTP_REFERER")
        self._site_title = os.getenv("OPENROUTER_SITE_TITLE") or os.getenv("OPENROUTER_SITE_NAME")
        self._vision_model = os.getenv("OPENROUTER_VISION_MODEL") or OPENROUTER_DEFAULT_VISION_MODEL

    @property
    def base_url(self) -> str:
        return self._base_url

    def _build_chat_url(self) -> str:
        return f"{self._base_url}/chat/completions"

    def _build_models_url(self) -> str:
        return f"{self._base_url}/models"

    def _resolve_model(self, model: str, has_images: bool = False) -> str:
        # If payload contains images, use vision model unless explicitly overridden
        if has_images:
            vision_override = os.getenv("OPENROUTER_VISION_MODEL")
            if vision_override:
                return vision_override.strip()
            # Use default vision model since most text models don't support images
            return self._vision_model

        override = os.getenv("OPENROUTER_MODEL") or os.getenv("OPENROUTER_DEFAULT_MODEL")
        if override:
            return override.strip()
        model = (model or "").strip()
        if not model:
            raise ValueError("model is required")
        if "/" in model:
            return model
        return f"google/{model}"

    def _payload_has_images(self, payload: dict[str, Any]) -> bool:
        """Check if the payload contains image data."""
        contents = payload.get("contents") or []
        for content in contents:
            if not isinstance(content, dict):
                continue
            parts = content.get("parts") or []
            for part in parts:
                if not isinstance(part, dict):
                    continue
                if "inline_data" in part:
                    return True

        # Also check OpenRouter-style messages format
        messages = payload.get("messages") or []
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        return True
        return False

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._site_url:
            headers["HTTP-Referer"] = self._site_url
        if self._site_title:
            headers["X-Title"] = self._site_title
        return headers

    def _parts_to_content(self, parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str):
                content.append({"type": "text", "text": text})
                continue
            inline = part.get("inline_data")
            if isinstance(inline, dict):
                data = inline.get("data")
                mime_type = inline.get("mime_type") or "application/octet-stream"
                if isinstance(data, str) and data:
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{data}"},
                        }
                    )
        return content

    def _payload_to_messages(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if "messages" in payload:
            messages = payload.get("messages")
            if isinstance(messages, list):
                return messages
        contents = payload.get("contents") or []
        messages: list[dict[str, Any]] = []
        for content in contents:
            if not isinstance(content, dict):
                continue
            parts = content.get("parts") or []
            message_content = self._parts_to_content(parts)
            if not message_content:
                continue
            role = content.get("role") or "user"
            if role not in {"user", "assistant", "system"}:
                role = "user"
            messages.append({"role": role, "content": message_content})
        return messages

    def _extract_text_from_message(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    text = part.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
            return "".join(chunks)
        return ""

    async def generate_content(
        self,
        model: str,
        payload: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        has_images = self._payload_has_images(payload)
        resolved_model = self._resolve_model(model, has_images=has_images)
        if has_images:
            logger.info("Image detected in payload, using vision model: %s", resolved_model)
        messages = self._payload_to_messages(payload)
        if not messages:
            raise GoogleAIRequestError("No messages provided for OpenRouter request")

        request_payload: dict[str, Any] = {"model": resolved_model, "messages": messages}

        generation = payload.get("generationConfig") or {}
        if isinstance(generation, dict):
            temperature = generation.get("temperature")
            max_tokens = generation.get("maxOutputTokens")
            top_p = generation.get("topP")
            if isinstance(temperature, (int, float)):
                request_payload["temperature"] = temperature
            if isinstance(max_tokens, int):
                request_payload["max_tokens"] = max_tokens
            if isinstance(top_p, (int, float)):
                request_payload["top_p"] = top_p

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    self._build_chat_url(),
                    json=request_payload,
                    headers=self._headers(),
                )
        except httpx.TimeoutException as exc:
            raise GoogleAIRequestError("Request timed out") from exc
        except httpx.RequestError as exc:
            logger.error("OpenRouter request failed: %s", exc)
            raise GoogleAIRequestError(f"Request failed: {exc}") from exc

        if response.status_code == 429:
            raise GoogleAIRateLimitError("Rate limit exceeded. Please try again later.")
        if response.status_code != 200:
            raise GoogleAIRequestError(
                f"API request failed with status {response.status_code}: {response.text}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise GoogleAIParseError(f"Failed to parse OpenRouter response: {exc}") from exc

        # Check for error in response body (OpenRouter can return 200 with error)
        if "error" in data:
            error_info = data["error"]
            error_msg = (
                error_info.get("message", str(error_info))
                if isinstance(error_info, dict)
                else str(error_info)
            )
            raise GoogleAIRequestError(f"OpenRouter API error: {error_msg}")

        choices = data.get("choices") or []
        message = choices[0].get("message") if choices else {}
        content = message.get("content") if isinstance(message, dict) else ""
        text = self._extract_text_from_message(content)
        if not text.strip():
            raise GoogleAIParseError("Empty response from AI")

        return {
            "candidates": [
                {"content": {"parts": [{"text": text}]}},
            ]
        }

    async def check_health(self, timeout: float = 10.0) -> tuple[bool, str | None]:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(self._build_models_url(), headers=self._headers())
        except Exception as exc:
            logger.error("OpenRouter health check error: %s", exc, exc_info=True)
            return False, str(exc)[:200]

        if response.status_code == 200:
            return True, None

        preview = response.text[:200] if response.text else ""
        logger.warning("OpenRouter health check failed: %s %s", response.status_code, preview)
        return False, f"status_{response.status_code}: {preview}"


def extract_text(response_data: dict[str, Any]) -> str:
    candidates = response_data.get("candidates", [])
    if not candidates:
        raise GoogleAIParseError("No response generated by AI")

    content = candidates[0].get("content", {})
    parts = content.get("parts", [])
    for part in parts:
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            return text

    raise GoogleAIParseError("Empty response from AI")


def extract_json_from_text(text_response: str) -> dict[str, Any]:
    json_start = text_response.find("{")
    json_end = text_response.rfind("}") + 1
    if json_start == -1 or json_end <= 0:
        raise GoogleAIParseError(f"Could not find JSON in response: {text_response}")
    json_str = text_response[json_start:json_end]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise GoogleAIParseError(f"Failed to parse AI response as JSON: {exc}") from exc


def extract_json(response_data: dict[str, Any]) -> dict[str, Any]:
    return extract_json_from_text(extract_text(response_data))


_client: Any | None = None
_client_provider: str | None = None


def get_ai_provider() -> str:
    return _normalize_provider(os.getenv("AI_PROVIDER") or os.getenv("GEMINI_PROVIDER"))


def get_google_ai_client() -> Any:
    global _client
    global _client_provider
    provider = get_ai_provider()
    if _client is None or _client_provider != provider:
        _client = OpenRouterAIClient() if provider == "openrouter" else GoogleAIClient()
        _client_provider = provider
    return _client
