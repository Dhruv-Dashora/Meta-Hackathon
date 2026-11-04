"""Meta Muse Spark client (Responses API via httpx).

Endpoint: POST {base_url}/responses, model muse-spark-1.3.
Auth: Bearer MODEL_API_KEY (backend env only — never logged or returned).
Official docs: https://dev.meta.ai/docs/quickstart
              https://dev.meta.ai/docs/image-understanding
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.core.errors import SentinelError
from app.core.logging import get_logger

logger = get_logger(__name__)
# Diagnostic lines below are INFO so routine calls stay quiet-yet-visible.
logger.setLevel(logging.INFO)


class MuseSparkClient:
    """Minimal client sending one image + instruction per request."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: float | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        from app.core.config import settings  # deferred import for tests

        self._api_key = api_key if api_key is not None else settings.model_api_key
        self._base_url = (base_url or settings.muse_spark_base_url).rstrip("/")
        self._model = model or settings.muse_spark_model
        self._timeout_s = (
            timeout_s if timeout_s is not None else settings.muse_spark_timeout_s
        )
        self._http_client = http_client

    def analyze_image(self, image_data_url: str, instruction: str) -> str:
        """Send one image + instruction; return the model's output text.

        Single attempt, no automatic retries: a retry would double API
        cost on every slow call. Timeouts and transport errors are
        logged with elapsed time and failure stage only — never keys,
        headers, images, or prompt text.
        """
        if not self._api_key:
            raise SentinelError(
                "model_api_key_missing", "MODEL_API_KEY is not configured."
            )
        payload = {
            "model": self._model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": instruction},
                        {"type": "input_image", "image_url": image_data_url},
                    ],
                }
            ],
        }
        url = f"{self._base_url}/responses"
        # Sizes only: model, URL, instruction chars, payload bytes.
        logger.info(
            "Muse Spark request: model=%s url=%s instruction=%dch payload=%db",
            self._model,
            url,
            len(instruction),
            len(image_data_url),
        )
        started = time.perf_counter()
        try:
            if self._http_client is not None:
                response = self._http_client.post(
                    url,
                    headers=self._auth_headers(),
                    json=payload,
                    timeout=self._timeout_s,
                )
            else:
                with httpx.Client(timeout=self._timeout_s) as client:
                    response = client.post(
                        url,
                        headers=self._auth_headers(),
                        json=payload,
                        timeout=self._timeout_s,
                    )
        except httpx.TimeoutException as exc:
            elapsed = time.perf_counter() - started
            logger.warning(
                "Muse Spark timeout: stage=%s elapsed=%.2fs timeout=%.1fs",
                type(exc).__name__,
                elapsed,
                self._timeout_s,
            )
            raise SentinelError(
                "muse_spark_timeout", "Muse Spark request timed out."
            ) from exc
        except httpx.HTTPError as exc:
            elapsed = time.perf_counter() - started
            logger.warning(
                "Muse Spark transport error: stage=%s elapsed=%.2fs",
                type(exc).__name__,
                elapsed,
            )
            raise SentinelError(
                "muse_spark_transport_error", "Muse Spark request failed."
            ) from exc
        elapsed = time.perf_counter() - started
        logger.info(
            "Muse Spark response: http=%s elapsed=%.2fs",
            response.status_code,
            elapsed,
        )
        if response.status_code >= 400:
            raise SentinelError(
                "muse_spark_http_error",
                f"Muse Spark returned HTTP {response.status_code}.",
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise SentinelError(
                "muse_spark_bad_response", "Muse Spark returned invalid JSON."
            ) from exc
        text = extract_output_text(body)
        if not text:
            raise SentinelError(
                "muse_spark_empty_output", "Muse Spark returned no output text."
            )
        logger.info("Muse Spark output text: %d chars", len(text))
        return text

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}


def extract_output_text(body: Any) -> str:
    """Best-effort output-text extraction across Responses-API shapes."""
    if isinstance(body, dict):
        direct = body.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        output = body.get("output")
        if isinstance(output, list):
            for item in output:
                text = _item_text(item)
                if text:
                    return text
        choices = body.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message", {})
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        return content.strip()
    return ""


def _item_text(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        return ""
    text = item.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    content = item.get("content")
    if isinstance(content, list):
        for part in content:
            found = _item_text(part)
            if found:
                return found
    elif isinstance(content, str) and content.strip():
        return content.strip()
    return ""
