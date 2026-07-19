import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.models import ExtractedLabel
from scripts import extract_sample as benchmark


def _image_bytes() -> bytes:
    image = Image.new("RGB", (120, 200), (170, 140, 110))
    output = BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


def test_degraded_variants_are_deterministic_decodable_and_complete() -> None:
    first = benchmark.degraded_variants(_image_bytes())
    second = benchmark.degraded_variants(_image_bytes())

    assert [variant.name for variant in first] == [
        "rotation",
        "blur",
        "perspective",
        "glare",
        "shadow-low-light",
        "compression",
        "crop",
    ]
    assert [variant.data for variant in first] == [variant.data for variant in second]
    assert [variant.severity for variant in first].count("severe") == 1
    for variant in first:
        with Image.open(BytesIO(variant.data)) as image:
            image.verify()


def test_private_corpus_manifest_loads_without_exposing_image_names(
    tmp_path: Path,
) -> None:
    (tmp_path / "private-label.jpg").write_bytes(_image_bytes())
    manifest = {
        "labels": [
            {
                "image": "private-label.jpg",
                "warning_bbox": [0.1, 0.5, 0.9, 0.8],
                "expected": benchmark.DEFAULT_EXPECTED,
            }
        ]
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    labels = benchmark.load_corpus(tmp_path)

    assert labels[0].name == "label-1"
    assert labels[0].expected == benchmark.DEFAULT_EXPECTED


def test_private_corpus_rejects_paths_outside_directory(tmp_path: Path) -> None:
    manifest = {
        "labels": [
            {
                "image": "../secret.jpg",
                "warning_bbox": [0.1, 0.5, 0.9, 0.8],
                "expected": benchmark.DEFAULT_EXPECTED,
            }
        ]
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="stay inside"):
        benchmark.load_corpus(tmp_path)


def test_benchmark_warning_score_is_exact_and_case_sensitive() -> None:
    extracted = ExtractedLabel(**benchmark.DEFAULT_EXPECTED)
    exact = benchmark._case_score(benchmark.DEFAULT_EXPECTED, extracted)
    wrong_caps = benchmark._case_score(
        benchmark.DEFAULT_EXPECTED,
        extracted.model_copy(
            update={
                "government_warning": benchmark.DEFAULT_EXPECTED[
                    "government_warning"
                ].replace("GOVERNMENT WARNING", "Government Warning", 1)
            }
        ),
    )

    assert exact["warning_exact"] is True
    assert exact["verdict"] == "PASS"
    assert wrong_caps["warning_exact"] is False
    assert wrong_caps["verdict"] == "NEEDS_REVIEW"


def test_benchmark_records_preprocess_provider_comparison_and_total(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "private.jpg"
    image_path.write_bytes(_image_bytes())

    class FakeVisionService:
        def __init__(self, **_kwargs: object) -> None:
            self.last_usage = {"prompt_tokens": 10, "completion_tokens": 5}

        def extract_preprocessed(self, _data: bytes) -> ExtractedLabel:
            return ExtractedLabel(**benchmark.DEFAULT_EXPECTED)

    monkeypatch.setattr("app.vision.VisionService", FakeVisionService)
    result = benchmark._run_configuration(
        [
            benchmark.CorpusLabel(
                "label-1",
                image_path,
                benchmark.DEFAULT_EXPECTED,
                (0.1, 0.5, 0.9, 0.8),
            )
        ],
        model="gpt-4o-mini",
        max_long_side=1280,
        jpeg_quality=82,
        prompt_name="current",
        runs=1,
        include_variants=False,
        case_names=None,
    )

    record = result["records"][0]
    assert record["preprocess_seconds"] >= 0
    assert record["provider_seconds"] >= 0
    assert record["comparison_seconds"] >= 0
    assert record["total_seconds"] >= sum(
        record[name]
        for name in (
            "preprocess_seconds",
            "provider_seconds",
            "comparison_seconds",
        )
    ) - 0.000002
    assert result["summary"]["preprocess_p95_seconds"] >= 0
    assert result["summary"]["comparison_p95_seconds"] >= 0
