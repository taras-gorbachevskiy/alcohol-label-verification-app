#!/usr/bin/env python3
"""Run the production acceptance checklist against a deployed service.

The JSON report contains only case names, response statuses, verdicts, field
statuses, and timings. It never contains expected/extracted label text or image
contents.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models import BatchVerificationResult, VerificationResult
from scripts.extract_sample import (
    DEFAULT_EXPECTED,
    DEFAULT_SAMPLE,
    degraded_variants,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="deployed origin, such as https://example.test")
    parser.add_argument(
        "--json-output",
        type=Path,
        help="optional privacy-safe report path",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.0,
        help="pause between paid provider calls to stay below provider throughput limits",
    )
    return parser.parse_args()


def _multipart_image(data: bytes, *, name: str = "label.jpg", mime: str = "image/jpeg") -> tuple[str, bytes, str]:
    return name, data, mime


def _field_statuses(result: VerificationResult) -> dict[str, str]:
    return {field.field: field.status for field in result.fields}


class AcceptanceRun:
    def __init__(self, url: str, *, delay_seconds: float = 0.0) -> None:
        self.url = url.rstrip("/")
        self.client = httpx.Client(timeout=10.0, follow_redirects=False)
        self.delay_seconds = max(0.0, delay_seconds)
        self.records: list[dict[str, Any]] = []
        self.failures: list[str] = []

    def close(self) -> None:
        self.client.close()

    def require(self, condition: bool, case: str, detail: str) -> None:
        if not condition:
            self.failures.append(f"{case}: {detail}")

    def verify(
        self,
        case: str,
        application: dict[str, str],
        image: bytes,
        *,
        expected_verdict: str | None,
        expected_failures: set[str] | None = None,
        warning_exact_or_null: bool = False,
    ) -> VerificationResult | None:
        started = time.perf_counter()
        response = self.client.post(
            f"{self.url}/verify",
            files={"image": _multipart_image(image)},
            data={"application": json.dumps(application)},
        )
        elapsed_ms = round((time.perf_counter() - started) * 1_000, 2)
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        record: dict[str, Any] = {
            "case": case,
            "http_status": response.status_code,
            "request_ms": elapsed_ms,
        }
        try:
            result = VerificationResult.model_validate(response.json())
        except Exception as exc:  # noqa: BLE001 - acceptance report must continue
            record["parse_error"] = type(exc).__name__
            self.records.append(record)
            self.require(False, case, f"expected typed result, got HTTP {response.status_code}")
            return None

        statuses = _field_statuses(result)
        warning = next(field for field in result.fields if field.field == "government_warning")
        warning_state = (
            "null"
            if warning.actual is None
            else "exact"
            if warning.actual == DEFAULT_EXPECTED["government_warning"]
            else "other"
        )
        record.update(
            {
                "verdict": result.verdict,
                "server_ms": round(result.latency_ms, 2),
                "field_statuses": statuses,
                "warning_state": warning_state,
            }
        )
        self.records.append(record)
        self.require(response.status_code == 200, case, f"HTTP {response.status_code}, expected 200")
        if expected_verdict is not None:
            self.require(result.verdict == expected_verdict, case, f"verdict {result.verdict}, expected {expected_verdict}")
        if expected_failures is not None:
            actual_failures = {field for field, status in statuses.items() if status == "FAIL"}
            self.require(
                actual_failures == expected_failures,
                case,
                f"failed fields {sorted(actual_failures)}, expected {sorted(expected_failures)}",
            )
        if warning_exact_or_null:
            self.require(
                warning_state in {"exact", "null"},
                case,
                "degraded warning was neither exact nor null",
            )
        return result

    def invalid_requests(self) -> None:
        case = "wrong_file_type"
        started = time.perf_counter()
        response = self.client.post(
            f"{self.url}/verify",
            files={"image": _multipart_image(b"not an image", name="label.txt", mime="text/plain")},
            data={"application": json.dumps(DEFAULT_EXPECTED)},
        )
        elapsed_ms = round((time.perf_counter() - started) * 1_000, 2)
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        body = response.json()
        self.records.append(
            {
                "case": case,
                "http_status": response.status_code,
                "request_ms": elapsed_ms,
                "error_code": body.get("error", {}).get("code"),
            }
        )
        self.require(response.status_code == 415, case, f"HTTP {response.status_code}, expected 415")
        self.require(body.get("error", {}).get("code") == "UNSUPPORTED_IMAGE_TYPE", case, "wrong error code")

        case = "empty_submit"
        started = time.perf_counter()
        response = self.client.post(f"{self.url}/verify")
        elapsed_ms = round((time.perf_counter() - started) * 1_000, 2)
        body = response.json()
        self.records.append(
            {
                "case": case,
                "http_status": response.status_code,
                "request_ms": elapsed_ms,
                "error_code": body.get("error", {}).get("code"),
                "error_field": body.get("error", {}).get("field"),
            }
        )
        self.require(response.status_code == 422, case, f"HTTP {response.status_code}, expected 422")
        self.require(bool(body.get("error", {}).get("message")), case, "missing readable error message")

    def batch(self, image: bytes) -> None:
        mismatched = {**DEFAULT_EXPECTED, "brand": "NOT THE LABEL BRAND"}
        applications = [DEFAULT_EXPECTED, mismatched, DEFAULT_EXPECTED]
        files = [
            ("images", _multipart_image(image, name="approved.jpg")),
            ("images", _multipart_image(image, name="review.jpg")),
            ("images", _multipart_image(b"not an image", name="unable.txt", mime="text/plain")),
        ]
        started = time.perf_counter()
        response = self.client.post(
            f"{self.url}/verify/batch",
            files=files,
            data={"applications": json.dumps(applications)},
        )
        elapsed_ms = round((time.perf_counter() - started) * 1_000, 2)
        case = "batch_summary"
        record: dict[str, Any] = {
            "case": case,
            "http_status": response.status_code,
            "request_ms": elapsed_ms,
        }
        try:
            result = BatchVerificationResult.model_validate(response.json())
        except Exception as exc:  # noqa: BLE001
            record["parse_error"] = type(exc).__name__
            self.records.append(record)
            self.require(False, case, "response was not a typed batch result")
            return
        record.update(
            {
                "server_ms": round(result.latency_ms, 2),
                "summary": result.summary.model_dump(),
                "statuses": [item.status for item in result.items],
                "indexes": [item.index for item in result.items],
                "filenames": [item.filename for item in result.items],
            }
        )
        self.records.append(record)
        self.require(response.status_code == 200, case, f"HTTP {response.status_code}, expected 200")
        self.require(
            result.summary.model_dump()
            == {"passed": 1, "needs_review": 1, "unable_to_verify": 1, "total": 3},
            case,
            f"wrong counts {result.summary.model_dump()}",
        )
        self.require([item.index for item in result.items] == [0, 1, 2], case, "order was not preserved")
        self.require(
            [item.filename for item in result.items]
            == ["approved.jpg", "review.jpg", "unable.txt"],
            case,
            "filenames were not preserved",
        )

    def run(self) -> dict[str, Any]:
        image = DEFAULT_SAMPLE.read_bytes()
        exact = dict(DEFAULT_EXPECTED)

        self.verify("valid_label", exact, image, expected_verdict="PASS", expected_failures=set())
        self.verify(
            "single_mismatch",
            {**exact, "brand": "NOT THE LABEL BRAND"},
            image,
            expected_verdict="NEEDS_REVIEW",
            expected_failures={"brand"},
        )
        self.verify(
            "multiple_mismatches",
            {**exact, "brand": "NOT THE LABEL BRAND", "country": "France"},
            image,
            expected_verdict="NEEDS_REVIEW",
            expected_failures={"brand", "country"},
        )
        self.verify(
            "case_only_non_warning",
            {**exact, "brand": exact["brand"].title()},
            image,
            expected_verdict="PASS",
            expected_failures=set(),
        )
        self.verify(
            "abv_bare_number",
            {**exact, "abv": "13.5"},
            image,
            expected_verdict="PASS",
            expected_failures=set(),
        )
        self.verify(
            "abv_proof_normalization",
            {**exact, "abv": "13.5% Alc./Vol. (27 Proof)"},
            image,
            expected_verdict="PASS",
            expected_failures=set(),
        )
        for case, value in (
            ("volume_centiliters", "75 cL"),
            ("volume_liters", "0.75 L"),
            ("volume_fluid_ounces", "25.4 fl oz"),
        ):
            self.verify(
                case,
                {**exact, "net_contents": value},
                image,
                expected_verdict="PASS",
                expected_failures=set(),
            )
        self.verify(
            "warning_wrong_caps",
            {
                **exact,
                "government_warning": exact["government_warning"].replace(
                    "GOVERNMENT WARNING:", "Government Warning:", 1
                ),
            },
            image,
            expected_verdict="NEEDS_REVIEW",
            expected_failures={"government_warning"},
        )

        variants = degraded_variants(image, (0.07, 0.32, 0.70, 0.46))
        for variant in variants:
            self.verify(
                f"imperfect_{variant.name}",
                exact,
                variant.data,
                expected_verdict="NEEDS_REVIEW" if variant.severity == "severe" else None,
                warning_exact_or_null=True,
            )
        crop_result = next(
            (record for record in self.records if record["case"] == "imperfect_crop"),
            {},
        )
        self.require(crop_result.get("verdict") != "PASS", "warning_missing", "cropped warning produced PASS")
        self.require(crop_result.get("warning_state") == "null", "warning_missing", "cropped warning was not null")

        self.invalid_requests()
        self.batch(image)
        return {
            "url": self.url,
            "passed": not self.failures,
            "failures": self.failures,
            "records": self.records,
        }


def main() -> int:
    args = _parse_args()
    run = AcceptanceRun(args.url, delay_seconds=args.delay_seconds)
    try:
        report = run.run()
    finally:
        run.close()
    serialized = json.dumps(report, indent=2)
    print(serialized)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(serialized + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
