"""Image downscale / JPEG re-encode for vision API latency budget."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_LONG_SIDE = 1536
JPEG_QUALITY = 85
MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_INPUT_PIXELS = 50_000_000


class ImagePreprocessError(ValueError):
    """Raised when image bytes cannot be decoded or re-encoded."""


def preprocess_image(data: bytes) -> bytes:
    """Return JPEG bytes with longest side <= MAX_LONG_SIDE.

    Raises:
        ImagePreprocessError: corrupt or undecodable input.
    """
    if not data:
        raise ImagePreprocessError("empty image bytes")
    if len(data) > MAX_INPUT_BYTES:
        raise ImagePreprocessError("image exceeds byte limit")

    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_INPUT_PIXELS:
                raise ImagePreprocessError("image exceeds pixel limit")

            image.load()
            oriented = ImageOps.exif_transpose(image)
            if "A" in oriented.getbands() or "transparency" in oriented.info:
                rgba = oriented.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
            else:
                rgb = oriented.convert("RGB")
            rgb.thumbnail((MAX_LONG_SIDE, MAX_LONG_SIDE), Image.Resampling.LANCZOS)
            out = BytesIO()
            rgb.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            return out.getvalue()
    except ImagePreprocessError:
        raise
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise ImagePreprocessError(f"unable to preprocess image: {exc}") from exc
