from app.comparison import compare_labels
from app.models import ApplicationData, ExtractedLabel
from tests.warning_fixtures import ALL_CAPS_WARNING, TITLE_CASE_WARNING


def _matching_pair() -> tuple[ApplicationData, ExtractedLabel]:
    application = ApplicationData(
        brand="ACME WINE",
        class_type="Table Wine",
        producer="Acme Cellars",
        country="USA",
        abv="45%",
        net_contents="750 mL",
        government_warning=ALL_CAPS_WARNING,
    )
    extracted = ExtractedLabel(
        brand="acme wine",
        class_type="table wine",
        producer="Acme Cellars",
        country="United States",
        abv="45% Alc./Vol. (90 Proof)",
        net_contents="750ml",
        government_warning=ALL_CAPS_WARNING,
    )
    return application, extracted


def test_all_fields_match_verdict_pass() -> None:
    application, extracted = _matching_pair()
    result = compare_labels(application, extracted)
    assert result.verdict == "PASS"
    assert len(result.fields) == 7
    assert all(f.status == "PASS" for f in result.fields)


def test_single_fuzzy_fail_needs_review() -> None:
    application, extracted = _matching_pair()
    extracted = extracted.model_copy(update={"brand": "Completely Different Brand"})
    result = compare_labels(application, extracted)
    assert result.verdict == "NEEDS_REVIEW"
    brand = next(f for f in result.fields if f.field == "brand")
    assert brand.status == "FAIL"


def test_warning_case_mismatch_only_needs_review() -> None:
    application, extracted = _matching_pair()
    extracted = extracted.model_copy(update={"government_warning": TITLE_CASE_WARNING})
    result = compare_labels(application, extracted)
    assert result.verdict == "NEEDS_REVIEW"
    warning = next(f for f in result.fields if f.field == "government_warning")
    assert warning.status == "FAIL"
    assert warning.actual == TITLE_CASE_WARNING
    assert all(
        f.status == "PASS"
        for f in result.fields
        if f.field != "government_warning"
    )


def test_multiple_fails_still_needs_review() -> None:
    application, extracted = _matching_pair()
    extracted = extracted.model_copy(
        update={
            "brand": "Wrong Brand",
            "country": "France",
            "government_warning": TITLE_CASE_WARNING,
        }
    )
    result = compare_labels(application, extracted)
    assert result.verdict == "NEEDS_REVIEW"
    failing = {f.field for f in result.fields if f.status == "FAIL"}
    assert failing >= {"brand", "country", "government_warning"}
