import pytest
from pydantic import ValidationError

from app.models import (
    ApplicationData,
    ExtractedLabel,
    FieldResult,
    VerificationApplicationData,
    VerificationResult,
)


def test_application_data_round_trip() -> None:
    payload = {
        "brand": "Acme",
        "class_type": "Whiskey",
        "producer": "Acme Distilling",
        "country": "USA",
        "abv": "45%",
        "net_contents": "750 mL",
        "government_warning": "GOVERNMENT WARNING: test",
    }
    data = ApplicationData(**payload)
    assert data.model_dump() == payload


def test_extracted_label_round_trip() -> None:
    payload = {
        "brand": "acme",
        "class_type": "whiskey",
        "producer": "Acme Distilling",
        "country": "United States",
        "abv": "45% Alc./Vol. (90 Proof)",
        "net_contents": "750ml",
        "government_warning": "GOVERNMENT WARNING: test",
    }
    data = ExtractedLabel(**payload)
    assert data.model_dump() == payload


def test_field_result_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        FieldResult(
            field="brand",
            status="MAYBE",  # type: ignore[arg-type]
            expected="a",
            actual="b",
            score=None,
            detail=None,
        )


def test_verification_result_rejects_invalid_verdict() -> None:
    with pytest.raises(ValidationError):
        VerificationResult(
            verdict="PARTIAL",  # type: ignore[arg-type]
            fields=[],
            latency_ms=0.0,
        )


def test_verification_application_rejects_fields_over_2000_characters() -> None:
    payload = {
        "brand": "x" * 2_001,
        "class_type": "Whiskey",
        "producer": "Acme Distilling",
        "country": "USA",
        "abv": "45%",
        "net_contents": "750 mL",
        "government_warning": "GOVERNMENT WARNING: test",
    }

    with pytest.raises(ValidationError) as error:
        VerificationApplicationData.model_validate(payload)

    assert error.value.errors()[0]["type"] == "string_too_long"
