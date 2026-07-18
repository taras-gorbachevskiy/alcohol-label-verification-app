from io import BytesIO

import pytest
from PIL import Image

import app.vision.preprocess as preprocess_module
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


def test_preprocess_does_not_upscale_small_image() -> None:
    out = preprocess_image(_png_bytes(32, 24))
    with Image.open(BytesIO(out)) as image:
        assert image.size == (32, 24)


def test_preprocess_applies_exif_orientation() -> None:
    image = Image.new("RGB", (40, 20), (200, 180, 160))
    exif = Image.Exif()
    exif[274] = 6
    buf = BytesIO()
    image.save(buf, format="JPEG", exif=exif)

    out = preprocess_image(buf.getvalue())

    with Image.open(BytesIO(out)) as oriented:
        assert oriented.size == (20, 40)


def test_preprocess_composites_transparency_onto_white() -> None:
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    buf = BytesIO()
    image.save(buf, format="PNG")

    out = preprocess_image(buf.getvalue())

    with Image.open(BytesIO(out)) as flattened:
        red, green, blue = flattened.getpixel((4, 4))
        assert min(red, green, blue) >= 250


def test_preprocess_rejects_input_over_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preprocess_module, "MAX_INPUT_BYTES", 4)
    with pytest.raises(ImagePreprocessError, match="byte limit"):
        preprocess_image(_png_bytes(8, 8))


def test_preprocess_rejects_input_over_pixel_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preprocess_module, "MAX_INPUT_PIXELS", 100)
    with pytest.raises(ImagePreprocessError, match="pixel limit"):
        preprocess_image(_png_bytes(11, 10))


def test_preprocess_rejects_corrupt_bytes() -> None:
    with pytest.raises(ImagePreprocessError):
        preprocess_image(b"not-an-image")


def test_preprocess_rejects_empty_bytes() -> None:
    with pytest.raises(ImagePreprocessError):
        preprocess_image(b"")
