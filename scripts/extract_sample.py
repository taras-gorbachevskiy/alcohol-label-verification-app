#!/usr/bin/env python3
"""Opt-in live VisionService accuracy and latency check.

Usage:
  uv run python scripts/extract_sample.py
  uv run python scripts/extract_sample.py path/to/label.jpg --runs 3 --variants
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE = ROOT / "samples" / "sample_label.jpg"
MAX_SECONDS = 5.0

EXPECTED = {
    "brand": "RIVERBEND RESERVE",
    "class_type": "Cabernet Sauvignon",
    "producer": "Riverbend Winery",
    "country": "USA",
    "abv": "13.5% alc/vol",
    "net_contents": "750 mL",
    "government_warning": (
        "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
        "drink alcoholic beverages during pregnancy because of the risk of birth "
        "defects. (2) Consumption of alcoholic beverages impairs your ability to "
        "drive a car or operate machinery, and may cause health problems."
    ),
}

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="number of clean-image calls (default: 1)",
    )
    parser.add_argument(
        "--variants",
        action="store_true",
        help="also call the model with rotated, blurred, angled, and glare variants",
    )
    args = parser.parse_args(argv[1:])
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    return args


def _encode_jpeg(image: Image.Image) -> bytes:
    out = BytesIO()
    image.convert("RGB").save(out, format="JPEG", quality=90)
    return out.getvalue()


def _degraded_variants(data: bytes) -> list[tuple[str, bytes]]:
    with Image.open(BytesIO(data)) as source:
        image = source.convert("RGB")

    rotated = image.rotate(90, expand=True, fillcolor="white")
    blurred = image.filter(ImageFilter.GaussianBlur(radius=1.5))
    angled = image.rotate(8, expand=True, fillcolor="white")
    glare = image.copy()
    draw = ImageDraw.Draw(glare, "RGBA")
    width, height = glare.size
    draw.polygon(
        [
            (width * 0.42, 0),
            (width * 0.67, 0),
            (width * 0.45, height),
            (width * 0.20, height),
        ],
        fill=(255, 255, 255, 175),
    )
    return [
        ("rotated", _encode_jpeg(rotated)),
        ("blurred", _encode_jpeg(blurred)),
        ("angled", _encode_jpeg(angled)),
        ("glare", _encode_jpeg(glare)),
    ]


def _collapsed_whitespace(value: str) -> str:
    return " ".join(value.split())


def _clean_result_errors(label_data: dict[str, str | None]) -> list[str]:
    errors: list[str] = []
    for field, expected in EXPECTED.items():
        actual = label_data[field]
        if field == "government_warning" and actual is not None:
            matches = _collapsed_whitespace(actual) == _collapsed_whitespace(expected)
        else:
            matches = actual == expected
        if not matches:
            errors.append(f"{field}: expected {expected!r}, got {actual!r}")
    return errors


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    load_dotenv(ROOT / ".env")

    if not args.image.is_file():
        print(f"Sample image not found: {args.image}", file=sys.stderr)
        return 1

    # Import after dotenv so OPENAI_API_KEY is available.
    from app.vision import VisionService

    clean_bytes = args.image.read_bytes()
    inputs = [(f"clean-{index + 1}", clean_bytes) for index in range(args.runs)]
    if args.variants:
        inputs.extend(_degraded_variants(clean_bytes))

    try:
        service = VisionService()
    except RuntimeError as exc:
        print(f"Live check FAILED: {exc}", file=sys.stderr)
        return 1

    failures: list[str] = []
    durations: list[float] = []
    for name, image_bytes in inputs:
        started = time.perf_counter()
        try:
            label = service.extract(image_bytes)
        except RuntimeError as exc:
            failures.append(f"{name}: {exc}")
            continue
        elapsed = time.perf_counter() - started
        durations.append(elapsed)
        label_data = label.model_dump()
        print(json.dumps({"case": name, "seconds": elapsed, "label": label_data}, indent=2))

        if elapsed >= MAX_SECONDS:
            failures.append(f"{name}: {elapsed:.3f}s exceeded {MAX_SECONDS:.1f}s")
        if name.startswith("clean-"):
            failures.extend(f"{name}: {error}" for error in _clean_result_errors(label_data))

    if durations:
        print(
            "Latency: "
            f"p50={_percentile(durations, 0.50):.3f}s "
            f"p95={_percentile(durations, 0.95):.3f}s",
            file=sys.stderr,
        )

    if failures:
        for failure in failures:
            print(f"Live check FAILED: {failure}", file=sys.stderr)
        return 2

    print("Live check OK: accuracy and latency gates passed.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
