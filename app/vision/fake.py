"""Fake VisionService for tests — never calls a real API."""

from __future__ import annotations

from app.models import ExtractedLabel
from app.vision.preprocess import ImagePreprocessError, preprocess_image


class FakeVisionService:
    """Drop-in extract() stub that returns a fixed ExtractedLabel.

    Useful for Phase 3 HTTP tests without OpenAI. Optionally runs preprocess
    so corrupt bytes still map to an all-null result (same soft-fail contract).
    """

    def __init__(
        self,
        result: ExtractedLabel | None = None,
        *,
        run_preprocess: bool = True,
    ) -> None:
        self._result = result if result is not None else ExtractedLabel()
        self._run_preprocess = run_preprocess
        self.calls: list[tuple[bytes, str | None]] = []
        self.preprocessed_calls: list[bytes] = []

    def extract(
        self,
        image_bytes: bytes,
        content_type: str | None = None,
    ) -> ExtractedLabel:
        self.calls.append((image_bytes, content_type))
        if self._run_preprocess:
            try:
                jpeg_bytes = preprocess_image(image_bytes)
            except ImagePreprocessError:
                return ExtractedLabel()
        else:
            jpeg_bytes = image_bytes
        return self.extract_preprocessed(jpeg_bytes)

    def extract_preprocessed(self, jpeg_bytes: bytes) -> ExtractedLabel:
        self.preprocessed_calls.append(jpeg_bytes)
        return self._result
