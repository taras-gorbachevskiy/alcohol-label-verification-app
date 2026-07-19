from app.models import ExtractedLabel
from app.vision.postprocess import guard_warning_extraction, normalize_extracted_label
from tests.warning_fixtures import ALL_CAPS_WARNING, TITLE_CASE_WARNING


def test_normalize_line_wrap_then_guard_keeps_exact_warning() -> None:
    wrapped = ALL_CAPS_WARNING.replace(". (2)", ".\n(2)")
    extracted = ExtractedLabel(government_warning=wrapped)

    normalized = normalize_extracted_label(extracted)
    guarded = guard_warning_extraction(ALL_CAPS_WARNING, normalized)

    assert normalized.government_warning == ALL_CAPS_WARNING
    assert guarded.government_warning == ALL_CAPS_WARNING


def test_normalize_then_guard_nulls_title_case_warning() -> None:
    extracted = ExtractedLabel(government_warning=f"  {TITLE_CASE_WARNING}\n  ")

    normalized = normalize_extracted_label(extracted)
    guarded = guard_warning_extraction(ALL_CAPS_WARNING, normalized)

    assert normalized.government_warning == f"  {TITLE_CASE_WARNING}   "
    assert guarded.government_warning is None


def test_normalize_blank_fields_to_none() -> None:
    extracted = ExtractedLabel(brand="", class_type="  ", producer="Winery")

    result = normalize_extracted_label(extracted)

    assert result.brand is None
    assert result.class_type is None
    assert result.producer == "Winery"
