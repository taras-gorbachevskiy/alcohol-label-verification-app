#!/usr/bin/env python3
"""Opt-in, privacy-safe vision accuracy and latency benchmark.

Examples:
  uv run python scripts/extract_sample.py --runs 3 --variants
  uv run python scripts/extract_sample.py --corpus /private/labels --variants
  uv run python scripts/extract_sample.py --corpus /private/labels --matrix

Corpus directories contain ``manifest.json`` using the schema demonstrated by
``samples/benchmark-manifest.example.json``. Image files and extracted text are
never printed; only timings, byte counts, null flags, and match statuses appear.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE = ROOT / "samples" / "sample_label.jpg"
MAX_SECONDS = 5.0
PROVIDER_P95_SECONDS = 3.6
FIELD_NAMES = (
    "brand",
    "class_type",
    "producer",
    "country",
    "abv",
    "net_contents",
    "government_warning",
)
NON_WARNING_FIELDS = FIELD_NAMES[:-1]
IMAGE_PROFILES = ((1536, 85), (1280, 82), (1024, 80))
TOKEN_PRICES_PER_MILLION = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o-mini-2024-07-18": (0.15, 0.60),
    "gpt-4.1-mini-2025-04-14": (0.40, 1.60),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.4-nano-2026-03-17": (0.20, 1.25),
}

DEFAULT_EXPECTED = {
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


@dataclass(frozen=True)
class CorpusLabel:
    name: str
    image: Path
    expected: dict[str, str]
    warning_bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class Variant:
    name: str
    data: bytes
    severity: str


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--corpus", type=Path, help="private corpus directory")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--variants", action="store_true")
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        choices=(
            "clean",
            "rotation",
            "blur",
            "perspective",
            "glare",
            "shadow-low-light",
            "compression",
            "crop",
        ),
        help="limit live calls to clean plus selected variant names",
    )
    parser.add_argument("--matrix", action="store_true", help="screen all profiles, prompts, and models")
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--prompt", choices=("current", "compact"), default="current")
    parser.add_argument("--max-long-side", type=int, default=1280)
    parser.add_argument("--jpeg-quality", type=int, default=82)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args(argv[1:])
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    if args.max_long_side < 1:
        parser.error("--max-long-side must be positive")
    if not 1 <= args.jpeg_quality <= 95:
        parser.error("--jpeg-quality must be between 1 and 95")
    return args


def _encode_jpeg(image: Image.Image, quality: int = 85) -> bytes:
    out = BytesIO()
    image.convert("RGB").save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def degraded_variants(
    data: bytes,
    warning_bbox: tuple[float, float, float, float] | None = None,
) -> list[Variant]:
    """Create deterministic mild and severe camera-quality regressions."""

    with Image.open(BytesIO(data)) as source:
        image = source.convert("RGB")
    width, height = image.size

    rotated = image.rotate(8, expand=True, fillcolor="white")
    blurred = image.filter(ImageFilter.GaussianBlur(radius=1.5))
    perspective = image.transform(
        image.size,
        Image.Transform.QUAD,
        (
            width * 0.04,
            height * 0.02,
            0,
            height * 0.96,
            width,
            height,
            width * 0.96,
            0,
        ),
        resample=Image.Resampling.BICUBIC,
    )
    glare = image.copy()
    draw = ImageDraw.Draw(glare, "RGBA")
    draw.polygon(
        [(width * 0.42, 0), (width * 0.67, 0), (width * 0.45, height), (width * 0.20, height)],
        fill=(255, 255, 255, 175),
    )
    low_light = ImageEnhance.Brightness(image).enhance(0.45)
    compressed = _encode_jpeg(image, quality=35)
    # Deliberately cut through the known warning region. The public sample uses
    # the fallback boundary; private manifests provide a normalized bbox.
    warning_top = warning_bbox[1] if warning_bbox else 0.32
    warning_bottom = warning_bbox[3] if warning_bbox else 0.46
    crop_bottom = max(1, int(height * ((warning_top + warning_bottom) / 2)))
    cropped = image.crop((0, 0, width, crop_bottom))

    return [
        Variant("rotation", _encode_jpeg(rotated), "mild"),
        Variant("blur", _encode_jpeg(blurred), "mild"),
        Variant("perspective", _encode_jpeg(perspective), "mild"),
        Variant("glare", _encode_jpeg(glare), "mild"),
        Variant("shadow-low-light", _encode_jpeg(low_light), "mild"),
        Variant("compression", compressed, "mild"),
        Variant("crop", _encode_jpeg(cropped), "severe"),
    ]


def _validated_expected(value: Any, *, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(FIELD_NAMES):
        raise ValueError(f"{label}: expected must contain exactly the seven fields")
    if any(not isinstance(value[field], str) or not value[field].strip() for field in FIELD_NAMES):
        raise ValueError(f"{label}: expected fields must be nonblank strings")
    return {field: value[field] for field in FIELD_NAMES}


def load_corpus(directory: Path) -> list[CorpusLabel]:
    manifest_path = directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read {manifest_path}: {exc}") from exc
    entries = manifest.get("labels") if isinstance(manifest, dict) else None
    if not isinstance(entries, list) or not 1 <= len(entries) <= 20:
        raise ValueError("manifest labels must contain between 1 and 20 entries")

    labels: list[CorpusLabel] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("image"), str):
            raise ValueError(f"labels[{index}] must include an image path")
        relative = Path(entry["image"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"labels[{index}].image must stay inside the corpus")
        image = directory / relative
        if not image.is_file():
            raise ValueError(f"labels[{index}] image not found: {relative}")
        bbox_value = entry.get("warning_bbox")
        if (
            not isinstance(bbox_value, list)
            or len(bbox_value) != 4
            or not all(isinstance(number, (int, float)) for number in bbox_value)
        ):
            raise ValueError(f"labels[{index}].warning_bbox must contain four numbers")
        bbox = tuple(float(number) for number in bbox_value)
        if not (
            0 <= bbox[0] < bbox[2] <= 1
            and 0 <= bbox[1] < bbox[3] <= 1
        ):
            raise ValueError(f"labels[{index}].warning_bbox must be normalized")
        labels.append(
            CorpusLabel(
                name=f"label-{index + 1}",
                image=image,
                expected=_validated_expected(entry.get("expected"), label=f"labels[{index}]"),
                warning_bbox=bbox,  # type: ignore[arg-type]
            )
        )
    return labels


def _dimensions(data: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(data)) as image:
        return image.size


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _case_score(expected: dict[str, str], actual: Any) -> dict[str, Any]:
    from app.comparison import compare_labels
    from app.models import ApplicationData

    result = compare_labels(ApplicationData(**expected), actual)
    statuses = {field.field: field.status for field in result.fields}
    warning = actual.government_warning
    return {
        "verdict": result.verdict,
        "field_statuses": statuses,
        "null_fields": [field for field in FIELD_NAMES if getattr(actual, field) is None],
        "warning_exact": warning == expected["government_warning"],
        "warning_null": warning is None,
        "non_warning_matches": sum(statuses[field] == "PASS" for field in NON_WARNING_FIELDS),
    }


def _estimated_cost(model: str, usage: dict[str, Any] | None) -> float | None:
    prices = TOKEN_PRICES_PER_MILLION.get(model)
    if not prices or not usage:
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if not isinstance(prompt, int) or not isinstance(completion, int):
        return None
    return (prompt * prices[0] + completion * prices[1]) / 1_000_000


def _configurations(args: argparse.Namespace) -> list[tuple[str, int, int, str]]:
    from app.vision.prompt import COMPACT_SYSTEM_PROMPT, SYSTEM_PROMPT
    from app.vision.service import BENCHMARK_MODELS, DEFAULT_MODEL

    prompts = {"current": SYSTEM_PROMPT, "compact": COMPACT_SYSTEM_PROMPT}
    if not args.matrix:
        return [((args.models or [DEFAULT_MODEL])[0], args.max_long_side, args.jpeg_quality, args.prompt)]
    models = tuple(args.models) if args.models else BENCHMARK_MODELS
    return [
        (model, side, quality, prompt_name)
        for model in models
        for side, quality in IMAGE_PROFILES
        for prompt_name in prompts
    ]


def _run_configuration(
    labels: list[CorpusLabel],
    *,
    model: str,
    max_long_side: int,
    jpeg_quality: int,
    prompt_name: str,
    runs: int,
    include_variants: bool,
    case_names: set[str] | None,
) -> dict[str, Any]:
    from app.vision import VisionService
    from app.vision.preprocess import preprocess_image
    from app.vision.prompt import COMPACT_SYSTEM_PROMPT, SYSTEM_PROMPT

    prompt = SYSTEM_PROMPT if prompt_name == "current" else COMPACT_SYSTEM_PROMPT
    service = VisionService(model=model, system_prompt=prompt, image_detail="high")
    records: list[dict[str, Any]] = []

    for label in labels:
        source = label.image.read_bytes()
        cases = [Variant("clean", source, "clean")]
        if include_variants:
            cases.extend(degraded_variants(source, label.warning_bbox))
        if case_names:
            selected = {"clean", *case_names}
            cases = [case for case in cases if case.name in selected]
        for repetition in range(runs):
            for variant in cases:
                preprocess_started = time.perf_counter()
                processed = preprocess_image(
                    variant.data,
                    max_long_side=max_long_side,
                    jpeg_quality=jpeg_quality,
                )
                preprocess_seconds = time.perf_counter() - preprocess_started
                provider_started = time.perf_counter()
                extracted = service.extract_preprocessed(processed)
                provider_seconds = time.perf_counter() - provider_started
                comparison_started = time.perf_counter()
                score = _case_score(label.expected, extracted)
                comparison_seconds = time.perf_counter() - comparison_started
                records.append(
                    {
                        "case": f"{label.name}-{variant.name}-{repetition + 1}",
                        "severity": variant.severity,
                        "source_dimensions": _dimensions(variant.data),
                        "processed_dimensions": _dimensions(processed),
                        "source_bytes": len(variant.data),
                        "processed_bytes": len(processed),
                        "preprocess_seconds": round(preprocess_seconds, 6),
                        "provider_seconds": round(provider_seconds, 6),
                        "comparison_seconds": round(comparison_seconds, 6),
                        "total_seconds": round(
                            preprocess_seconds + provider_seconds + comparison_seconds,
                            6,
                        ),
                        "usage": service.last_usage,
                        "estimated_cost_usd": _estimated_cost(model, service.last_usage),
                        **score,
                    }
                )

    clean = [record for record in records if record["severity"] == "clean"]
    mild = [record for record in records if record["severity"] == "mild"]
    severe = [record for record in records if record["severity"] == "severe"]
    provider_times = [record["provider_seconds"] for record in records]
    total_times = [record["total_seconds"] for record in records]
    mild_field_total = len(mild) * len(NON_WARNING_FIELDS)
    mild_matches = sum(record["non_warning_matches"] for record in mild)
    costs = [
        record["estimated_cost_usd"]
        for record in records
        if record["estimated_cost_usd"] is not None
    ]
    summary = {
        "model": model,
        "max_long_side": max_long_side,
        "jpeg_quality": jpeg_quality,
        "prompt": prompt_name,
        "case_count": len(records),
        "provider_p50_seconds": _percentile(provider_times, 0.50),
        "provider_p95_seconds": _percentile(provider_times, 0.95),
        "preprocess_p95_seconds": _percentile(
            [record["preprocess_seconds"] for record in records], 0.95
        ),
        "comparison_p95_seconds": _percentile(
            [record["comparison_seconds"] for record in records], 0.95
        ),
        "total_p95_seconds": _percentile(total_times, 0.95),
        "max_seconds": max(total_times),
        "processed_bytes_p95": _percentile([record["processed_bytes"] for record in records], 0.95),
        "mean_estimated_cost_usd": sum(costs) / len(costs) if costs else None,
        "clean_pass_rate": sum(record["verdict"] == "PASS" for record in clean) / len(clean),
        "clean_warning_exact_rate": sum(record["warning_exact"] for record in clean) / len(clean),
        "mild_non_warning_match_rate": mild_matches / mild_field_total if mild_field_total else None,
        "mild_warning_safe_rate": (
            sum(record["warning_exact"] or record["warning_null"] for record in mild) / len(mild)
            if mild
            else None
        ),
        "severe_false_passes": sum(record["verdict"] == "PASS" for record in severe),
        "gates": {
            "clean_all_pass": all(record["verdict"] == "PASS" for record in clean),
            "clean_warning_exact": all(record["warning_exact"] for record in clean),
            "provider_p95": _percentile(provider_times, 0.95) <= PROVIDER_P95_SECONDS,
            "all_under_five_seconds": max(total_times) < MAX_SECONDS,
            "payload_p95": _percentile([record["processed_bytes"] for record in records], 0.95) <= 1024 * 1024,
            "mild_fields": not mild or mild_matches / mild_field_total >= 0.95,
            "mild_warning_safe": not mild or all(record["warning_exact"] or record["warning_null"] for record in mild),
            "severe_no_false_pass": not severe or all(record["verdict"] != "PASS" for record in severe),
        },
    }
    return {"summary": summary, "records": records}


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    load_dotenv(ROOT / ".env")
    try:
        labels = (
            load_corpus(args.corpus)
            if args.corpus
            else [
                CorpusLabel(
                    "sample",
                    args.image,
                    DEFAULT_EXPECTED,
                    (0.07, 0.32, 0.70, 0.46),
                )
            ]
        )
        if any(not label.image.is_file() for label in labels):
            raise ValueError("benchmark image not found")
        screened_labels = labels[:3] if args.matrix else labels
        results = [
            _run_configuration(
                screened_labels,
                model=model,
                max_long_side=side,
                jpeg_quality=quality,
                prompt_name=prompt,
                runs=1 if args.matrix else args.runs,
                include_variants=args.variants or args.matrix or bool(args.cases),
                case_names=set(args.cases) if args.cases else None,
            )
            for model, side, quality, prompt in _configurations(args)
        ]
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"Live check FAILED: {exc}", file=sys.stderr)
        return 1

    report = {
        "corpus_size": len(labels),
        "screened_corpus_size": len(screened_labels),
        "configurations": results,
    }
    serialized = json.dumps(report, indent=2)
    print(serialized)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(serialized + "\n", encoding="utf-8")

    passing = [result for result in results if all(result["summary"]["gates"].values())]
    if not passing:
        print("Live check FAILED: no configuration passed every gate.", file=sys.stderr)
        return 2
    winner = min(
        passing,
        key=lambda result: (
            result["summary"]["provider_p95_seconds"],
            result["summary"]["mean_estimated_cost_usd"] or math.inf,
        ),
    )
    print(f"Live check OK: fastest passing configuration is {winner['summary']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
