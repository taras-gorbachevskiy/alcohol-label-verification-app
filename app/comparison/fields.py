from rapidfuzz import fuzz

from app.comparison.country_synonyms import canonicalize_country
from app.comparison.normalize import (
    ABV_TOLERANCE,
    FUZZY_THRESHOLD,
    NET_CONTENTS_RELATIVE_TOLERANCE,
    is_missing,
    parse_abv,
    parse_net_contents_ml,
    prep_fuzzy,
)
from app.models import FieldResult


def _missing_result(
    field: str,
    expected: str | None,
    actual: str | None,
) -> FieldResult | None:
    if is_missing(expected) or is_missing(actual):
        return FieldResult(
            field=field,
            status="FAIL",
            expected=expected,
            actual=actual,
            score=None,
            detail="missing value",
        )
    return None


def _compare_fuzzy(field: str, expected: str | None, actual: str | None) -> FieldResult:
    missing = _missing_result(field, expected, actual)
    if missing is not None:
        return missing

    assert expected is not None and actual is not None
    score = float(fuzz.token_sort_ratio(prep_fuzzy(expected), prep_fuzzy(actual)))
    status = "PASS" if score >= FUZZY_THRESHOLD else "FAIL"
    return FieldResult(
        field=field,
        status=status,
        expected=expected,
        actual=actual,
        score=score,
        detail=None if status == "PASS" else f"score {score} below {FUZZY_THRESHOLD}",
    )


def compare_brand(expected: str | None, actual: str | None) -> FieldResult:
    return _compare_fuzzy("brand", expected, actual)


def compare_class_type(expected: str | None, actual: str | None) -> FieldResult:
    return _compare_fuzzy("class_type", expected, actual)


def compare_producer(expected: str | None, actual: str | None) -> FieldResult:
    return _compare_fuzzy("producer", expected, actual)


def compare_country(expected: str | None, actual: str | None) -> FieldResult:
    missing = _missing_result("country", expected, actual)
    if missing is not None:
        return missing

    assert expected is not None and actual is not None
    left = canonicalize_country(expected)
    right = canonicalize_country(actual)
    status = "PASS" if left == right else "FAIL"
    return FieldResult(
        field="country",
        status=status,
        expected=expected,
        actual=actual,
        score=None,
        detail=None if status == "PASS" else f"canonical {left!r} != {right!r}",
    )


def compare_abv(expected: str | None, actual: str | None) -> FieldResult:
    missing = _missing_result("abv", expected, actual)
    if missing is not None:
        return missing

    assert expected is not None and actual is not None
    left = parse_abv(expected)
    right = parse_abv(actual)
    if left is None or right is None:
        return FieldResult(
            field="abv",
            status="FAIL",
            expected=expected,
            actual=actual,
            score=None,
            detail="unparseable abv",
        )
    status = "PASS" if abs(left - right) <= ABV_TOLERANCE else "FAIL"
    return FieldResult(
        field="abv",
        status=status,
        expected=expected,
        actual=actual,
        score=None,
        detail=None if status == "PASS" else f"{left} vs {right}",
    )


def compare_net_contents(expected: str | None, actual: str | None) -> FieldResult:
    missing = _missing_result("net_contents", expected, actual)
    if missing is not None:
        return missing

    assert expected is not None and actual is not None
    left = parse_net_contents_ml(expected)
    right = parse_net_contents_ml(actual)
    if left is None or right is None:
        return FieldResult(
            field="net_contents",
            status="FAIL",
            expected=expected,
            actual=actual,
            score=None,
            detail="unparseable net contents",
        )
    denom = max(left, right, 1.0)
    relative = abs(left - right) / denom
    status = "PASS" if relative <= NET_CONTENTS_RELATIVE_TOLERANCE else "FAIL"
    return FieldResult(
        field="net_contents",
        status=status,
        expected=expected,
        actual=actual,
        score=None,
        detail=None if status == "PASS" else f"{left} ml vs {right} ml",
    )


def compare_government_warning(expected: str | None, actual: str | None) -> FieldResult:
    """Exact, case-sensitive match with no normalization."""
    missing = _missing_result("government_warning", expected, actual)
    if missing is not None:
        return missing

    assert expected is not None and actual is not None
    status = "PASS" if expected == actual else "FAIL"
    return FieldResult(
        field="government_warning",
        status=status,
        expected=expected,
        actual=actual,
        score=None,
        detail=None if status == "PASS" else "exact case-sensitive mismatch",
    )
