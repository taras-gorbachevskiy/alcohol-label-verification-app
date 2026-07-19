from io import BytesIO

import pytest
from PIL import Image

import app.vision.preprocess as preprocess_module
from app.vision.preprocess import (
    MAX_LONG_SIDE,
    SKIP_REENCODE_MAX_BYTES,
    ImagePreprocessError,
    preprocess_image,
)


def _png_bytes(width: int, height: int, color: tuple[int, int, int] = (200, 180, 160)) -> bytes:
    image = Image.new("RGB", (width, height), color)
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(
    width: int,
    height: int,
    *,
    quality: int = 85,
    orientation: int | None = None,
) -> bytes:
    image = Image.new("RGB", (width, height), (200, 180, 160))
    buf = BytesIO()
    if orientation is None:
        image.save(buf, format="JPEG", quality=quality)
    else:
        exif = Image.Exif()
        exif[274] = orientation
        image.save(buf, format="JPEG", quality=quality, exif=exif)
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
        assert image.size == (MAX_LONG_SIDE, round(MAX_LONG_SIDE / 3))


def test_preprocess_does_not_upscale_small_image() -> None:
    out = preprocess_image(_png_bytes(32, 24))
    with Image.open(BytesIO(out)) as image:
        assert image.size == (32, 24)


def test_preprocess_accepts_phase6_tuning_profile() -> None:
    out = preprocess_image(
        _png_bytes(3000, 1000),
        max_long_side=1024,
        jpeg_quality=80,
    )
    with Image.open(BytesIO(out)) as image:
        assert image.size == (1024, 341)


@pytest.mark.parametrize(
    ("side", "quality"),
    [(0, 85), (1280, 0), (1280, 96)],
)
def test_preprocess_rejects_invalid_tuning_profile(side: int, quality: int) -> None:
    with pytest.raises(ValueError):
        preprocess_image(
            _png_bytes(8, 8),
            max_long_side=side,
            jpeg_quality=quality,
        )


def test_preprocess_skips_reencode_for_bounded_upright_jpeg() -> None:
    source = _jpeg_bytes(640, 480)
    assert len(source) <= SKIP_REENCODE_MAX_BYTES

    out = preprocess_image(source, content_type="image/jpeg")

    assert out is source


def test_preprocess_reencodes_jpeg_over_skip_byte_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _jpeg_bytes(640, 480)
    monkeypatch.setattr(preprocess_module, "SKIP_REENCODE_MAX_BYTES", 16)

    out = preprocess_image(source, content_type="image/jpeg")

    assert out != source
    assert out.startswith(b"\xff\xd8\xff")


def test_preprocess_reencodes_oversized_jpeg() -> None:
    source = _jpeg_bytes(3000, 1000)
    out = preprocess_image(source, content_type="image/jpeg")

    assert out != source
    with Image.open(BytesIO(out)) as image:
        assert max(image.size) <= MAX_LONG_SIDE


def test_preprocess_reencodes_oriented_jpeg() -> None:
    source = _jpeg_bytes(40, 20, orientation=6)
    out = preprocess_image(source, content_type="image/jpeg")

    assert out != source
    with Image.open(BytesIO(out)) as oriented:
        assert oriented.size == (20, 40)


def test_preprocess_reencodes_png_even_when_small() -> None:
    source = _png_bytes(64, 48)
    out = preprocess_image(source, content_type="image/png")

    assert out != source
    assert out.startswith(b"\xff\xd8\xff")


def test_preprocess_applies_exif_orientation() -> None:
    source = _jpeg_bytes(40, 20, orientation=6)

    out = preprocess_image(source)

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


def test_preprocess_accepts_matching_declared_content_type() -> None:
    out = preprocess_image(_png_bytes(8, 8), content_type="image/png")
    assert out.startswith(b"\xff\xd8\xff")


def test_preprocess_rejects_declared_content_type_mismatch() -> None:
    with pytest.raises(ImagePreprocessError) as exc_info:
        preprocess_image(_png_bytes(8, 8), content_type="image/jpeg")
    assert exc_info.value.reason == "image_type_mismatch"


def test_preprocess_rejects_unsupported_declared_content_type() -> None:
    with pytest.raises(ImagePreprocessError) as exc_info:
        preprocess_image(_png_bytes(8, 8), content_type="application/octet-stream")
    assert exc_info.value.reason == "unsupported_image_type"
