"""VisionService: image → ExtractedLabel via OpenAI structured outputs."""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ContentFilterFinishReasonError,
    InternalServerError,
    LengthFinishReasonError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from pydantic import ValidationError

from app.models import ExtractedLabel
from app.vision.preprocess import ImagePreprocessError, preprocess_image
from app.vision.prompt import SYSTEM_PROMPT, USER_PROMPT

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT_SECONDS = 4.0
MAX_COMPLETION_TOKENS = 400

_CONFIGURATION_ERRORS = (
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    UnprocessableEntityError,
)
_SOFT_API_ERRORS = (
    APIConnectionError,
    APITimeoutError,
    ContentFilterFinishReasonError,
    InternalServerError,
    LengthFinishReasonError,
    RateLimitError,
)


class VisionService:
    """Extract TTB label fields from an image.

    Pass ``client`` to inject a mock/stub (Phase 2/3 tests). When ``client`` is
    omitted, a live OpenAI client is built from ``OPENAI_API_KEY``.
    """

    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._model = model or os.environ.get("OPENAI_VISION_MODEL", DEFAULT_MODEL)
        if client is not None:
            self._client = client
        else:
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY is not set. Provide it via environment "
                    "or inject a client for tests."
                )
            self._client = OpenAI(
                api_key=api_key,
                timeout=timeout,
                max_retries=0,
            )

    def extract(
        self,
        image_bytes: bytes,
        content_type: str | None = None,  # noqa: ARG002 — reserved for callers
    ) -> ExtractedLabel:
        """Return ExtractedLabel; never raises for bad photos / soft API failures.

        Misconfiguration (invalid API key) raises — that is not a bad-photo case.
        """
        try:
            jpeg_bytes = preprocess_image(image_bytes)
        except ImagePreprocessError:
            logger.warning("image preprocess failed; returning empty ExtractedLabel")
            return ExtractedLabel()

        return self.extract_preprocessed(jpeg_bytes)

    def extract_preprocessed(self, jpeg_bytes: bytes) -> ExtractedLabel:
        """Extract fields from validated, bounded JPEG bytes.

        Callers are responsible for preprocessing before using this entry point.
        The existing :meth:`extract` method remains the safe public convenience
        API for unvalidated image bytes.
        """

        data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode(
            "ascii"
        )

        try:
            completion = self._client.chat.completions.parse(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": USER_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": data_url,
                                    "detail": "high",
                                },
                            },
                        ],
                    },
                ],
                response_format=ExtractedLabel,
                max_completion_tokens=MAX_COMPLETION_TOKENS,
            )
        except AuthenticationError as exc:
            raise RuntimeError(
                "OpenAI authentication failed. Check OPENAI_API_KEY."
            ) from exc
        except _CONFIGURATION_ERRORS as exc:
            raise RuntimeError(
                "OpenAI vision request configuration failed. "
                "Check OPENAI_VISION_MODEL and request settings."
            ) from exc
        except _SOFT_API_ERRORS as exc:
            logger.warning("vision API soft-fail: %s", type(exc).__name__)
            return ExtractedLabel()
        except ValidationError as exc:
            logger.warning("vision structured parse soft-fail: %s", type(exc).__name__)
            return ExtractedLabel()

        try:
            message = completion.choices[0].message
        except (AttributeError, IndexError, TypeError) as exc:
            logger.warning("vision response shape soft-fail: %s", exc)
            return ExtractedLabel()

        parsed = getattr(message, "parsed", None)
        if parsed is None:
            refusal = getattr(message, "refusal", None)
            if refusal:
                logger.warning("vision model refusal; returning empty ExtractedLabel")
            else:
                logger.warning("vision response had no parsed structured output")
            return ExtractedLabel()

        if isinstance(parsed, ExtractedLabel):
            return _normalize_empties(parsed)

        try:
            return _normalize_empties(ExtractedLabel.model_validate(parsed))
        except ValidationError as exc:
            logger.warning(
                "vision parsed validation soft-fail: %s",
                type(exc).__name__,
            )
            return ExtractedLabel()


def _normalize_empties(label: ExtractedLabel) -> ExtractedLabel:
    """Treat empty / whitespace-only strings as missing (None)."""
    data = label.model_dump()
    for key, value in data.items():
        if isinstance(value, str) and not value.strip():
            data[key] = None
    return ExtractedLabel(**data)
