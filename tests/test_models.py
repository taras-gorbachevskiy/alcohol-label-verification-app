import pytest
from pydantic import ValidationError

from app.models import (
    ApplicationData,
    ExtractedLabel,
    FieldResult,
    VerificationResult,
)


def test_application_data_accepts_all_fields() -> None:
    data = ApplicationData(
        brand="Acme",
        class_type="Whiskey",
        producer="Acme Distilling",
        country="USA",
        abv="45%",
        net_contents="750 mL",
        government_warning="GOVERNMENT WARNING: test",
    )
    assert data.brand == "Acme"
    assert data.class_type == "Whiskey"


def test_extracted_label_accepts_all_fields() -> None:
    data = ExtractedLabel(
        brand="acme",
        class_type="whiskey",
        producer="Acme Distilling",
        country="United States",
        abv="45% Alc./Vol. (90 Proof)",
        net_contents="750ml",
        government_warning="GOVERNMENT WARNING: test",
    )
    assert data.abv == "45% Alc./Vol. (90 Proof)"


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
        )
