"""Image downscale / JPEG re-encode for vision API latency budget."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, UnidentifiedImageError

MAX_LONG_SIDE = 1536
JPEG_QUALITY = 85


class ImagePreprocessError(ValueError):
    """Raised when image bytes cannot be decoded or re-encoded."""


def preprocess_image(data: bytes) -> bytes:
    """Return JPEG bytes with longest side <= MAX_LONG_SIDE.

    Raises:
        ImagePreprocessError: corrupt or undecodable input.
    """
    if not data:
        raise ImagePreprocessError("empty image bytes")

    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            rgb = image.convert("RGB")
            rgb.thumbnail((MAX_LONG_SIDE, MAX_LONG_SIDE), Image.Resampling.LANCZOS)
            out = BytesIO()
            rgb.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImagePreprocessError(f"unable to preprocess image: {exc}") from exc
