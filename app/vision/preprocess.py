"""Image downscale / JPEG re-encode for vision API latency budget."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_LONG_SIDE = 1280
JPEG_QUALITY = 82
MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_INPUT_PIXELS = 50_000_000
# Match the browser optimizer budget so client-preprocessed JPEGs are not
# re-encoded a second time before the vision provider call.
SKIP_REENCODE_MAX_BYTES = 1024 * 1024
SUPPORTED_CONTENT_TYPES = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


class ImagePreprocessError(ValueError):
    """Raised when image bytes cannot be decoded or re-encoded."""

    def __init__(self, message: str, *, reason: str = "invalid_image") -> None:
        super().__init__(message)
        self.reason = reason


def _exif_orientation(image: Image.Image) -> int:
    try:
        return int(image.getexif().get(0x0112, 1) or 1)
    except Exception:  # noqa: BLE001 - corrupt EXIF must not block preprocess
        return 1


def preprocess_image(
    data: bytes,
    content_type: str | None = None,
    *,
    max_long_side: int = MAX_LONG_SIDE,
    jpeg_quality: int = JPEG_QUALITY,
) -> bytes:
    """Return JPEG bytes with longest side <= MAX_LONG_SIDE.

    When ``content_type`` is supplied, enforce the endpoint's supported image
    formats and require the declared MIME type to match the decoded format.

    Already-bounded upright JPEGs under 1 MiB are returned unchanged to avoid
    a second lossy encode after browser-side optimization.

    Raises:
        ImagePreprocessError: corrupt or undecodable input.
    """
    if max_long_side < 1:
        raise ValueError("max_long_side must be positive")
    if not 1 <= jpeg_quality <= 95:
        raise ValueError("jpeg_quality must be between 1 and 95")
    if not data:
        raise ImagePreprocessError("empty image bytes", reason="empty_image")
    if len(data) > MAX_INPUT_BYTES:
        raise ImagePreprocessError("image exceeds byte limit", reason="image_too_large")

    expected_format: str | None = None
    if content_type is not None:
        expected_format = SUPPORTED_CONTENT_TYPES.get(content_type)
        if expected_format is None:
            raise ImagePreprocessError(
                "unsupported image content type",
                reason="unsupported_image_type",
            )

    try:
        with Image.open(BytesIO(data)) as image:
            decoded_format = image.format
            if expected_format is not None:
                if decoded_format not in SUPPORTED_CONTENT_TYPES.values():
                    raise ImagePreprocessError(
                        "unsupported decoded image format",
                        reason="unsupported_image_type",
                    )
                if decoded_format != expected_format:
                    raise ImagePreprocessError(
                        "declared MIME type does not match decoded image format",
                        reason="image_type_mismatch",
                    )

            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_INPUT_PIXELS:
                raise ImagePreprocessError(
                    "image exceeds pixel limit",
                    reason="image_too_large",
                )

            image.load()
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            orientation = _exif_orientation(image)
            if (
                decoded_format == "JPEG"
                and not has_alpha
                and orientation == 1
                and max(width, height) <= max_long_side
                and len(data) <= SKIP_REENCODE_MAX_BYTES
            ):
                return data

            oriented = ImageOps.exif_transpose(image)
            if "A" in oriented.getbands() or "transparency" in oriented.info:
                rgba = oriented.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
            else:
                rgb = oriented.convert("RGB")
            rgb.thumbnail((max_long_side, max_long_side), Image.Resampling.LANCZOS)
            out = BytesIO()
            rgb.save(out, format="JPEG", quality=jpeg_quality, optimize=True)
            return out.getvalue()
    except ImagePreprocessError:
        raise
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise ImagePreprocessError(
            f"unable to preprocess image: {exc}",
            reason="invalid_image",
        ) from exc
