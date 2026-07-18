from app.comparison.fields import compare_government_warning
from tests.warning_fixtures import (
    ALL_CAPS_WARNING,
    MISREAD_WARNING,
    MISSING_COLON_WARNING,
    TITLE_CASE_WARNING,
)


def test_correct_all_caps_warning_passes() -> None:
    """REVIEW #7: correct all-caps warning PASSES."""
    result = compare_government_warning(ALL_CAPS_WARNING, ALL_CAPS_WARNING)
    assert result.status == "PASS"
    assert result.expected == ALL_CAPS_WARNING
    assert result.actual == ALL_CAPS_WARNING
    assert result.score is None


def test_warning_whitespace_and_newlines_fail_exact_match() -> None:
    wrapped = ALL_CAPS_WARNING.replace(". (2)", ".\n(2)")
    result = compare_government_warning(ALL_CAPS_WARNING, wrapped)
    assert result.status == "FAIL"
    assert result.expected == ALL_CAPS_WARNING
    assert result.actual == wrapped


def test_title_case_warning_fails_strict_case_sensitive() -> None:
    """REVIEW #5: government warning in title case FAILS (strict case-sensitive)."""
    result = compare_government_warning(ALL_CAPS_WARNING, TITLE_CASE_WARNING)
    assert result.status == "FAIL"
    assert result.expected == ALL_CAPS_WARNING
    assert result.actual == TITLE_CASE_WARNING
    # Same letters ignoring case would match — our comparator must still FAIL.
    assert TITLE_CASE_WARNING.casefold() == ALL_CAPS_WARNING.casefold()


def test_warning_missing_colon_fails() -> None:
    """REVIEW #6: warning missing the colon FAILS."""
    result = compare_government_warning(ALL_CAPS_WARNING, MISSING_COLON_WARNING)
    assert result.status == "FAIL"
    assert result.expected == ALL_CAPS_WARNING
    assert result.actual == MISSING_COLON_WARNING


def test_misread_warning_returns_extracted_text() -> None:
    """REVIEW #8: a misread warning returns the extracted text in the result."""
    result = compare_government_warning(ALL_CAPS_WARNING, MISREAD_WARNING)
    assert result.status == "FAIL"
    assert result.actual == MISREAD_WARNING
    assert result.expected == ALL_CAPS_WARNING


def test_warning_missing_fails() -> None:
    result = compare_government_warning(ALL_CAPS_WARNING, None)
    assert result.status == "FAIL"
    assert result.actual is None
