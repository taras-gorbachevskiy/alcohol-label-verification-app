from io import BytesIO

import pytest
from PIL import Image

from app.vision.preprocess import (
    MAX_LONG_SIDE,
    ImagePreprocessError,
    preprocess_image,
)


def _png_bytes(width: int, height: int, color: tuple[int, int, int] = (200, 180, 160)) -> bytes:
    image = Image.new("RGB", (width, height), color)
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_preprocess_returns_jpeg() -> None:
    out = preprocess_image(_png_bytes(64, 48))
    assert out[:3] == b"\xff\xd8\xff"
    with Image.open(BytesIO(out)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"


def test_preprocess_downscales_long_side() -> None:
    out = preprocess_image(_png_bytes(3000, 1000))
    with Image.open(BytesIO(out)) as image:
        assert max(image.size) <= MAX_LONG_SIDE
        assert image.size == (MAX_LONG_SIDE, 512)


def test_preprocess_rejects_corrupt_bytes() -> None:
    with pytest.raises(ImagePreprocessError):
        preprocess_image(b"not-an-image")


def test_preprocess_rejects_empty_bytes() -> None:
    with pytest.raises(ImagePreprocessError):
        preprocess_image(b"")
