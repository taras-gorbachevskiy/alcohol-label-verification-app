from app.comparison.fields import compare_brand, compare_class_type, compare_producer


def test_brand_exact_match_passes_with_score_100() -> None:
    result = compare_brand("Acme Wine", "Acme Wine")
    assert result.status == "PASS"
    assert result.score == 100
    assert result.expected == "Acme Wine"
    assert result.actual == "Acme Wine"


def test_brand_case_only_diff_passes() -> None:
    """REVIEW #1: case-only brand diff passes."""
    result = compare_brand("ACME WINE", "acme wine")
    assert result.status == "PASS"
    assert result.score is not None
    assert result.score >= 85


def test_stakeholder_stones_throw_case_only_example_passes() -> None:
    result = compare_brand("STONE'S THROW", "Stone's Throw")
    assert result.status == "PASS"


def test_brand_extra_spaces_passes() -> None:
    result = compare_brand("ACME  WINE", "ACME WINE")
    assert result.status == "PASS"


def test_brand_token_order_passes() -> None:
    result = compare_brand("Valley Napa", "Napa Valley")
    assert result.status == "PASS"


def test_brand_unrelated_fails() -> None:
    result = compare_brand("Acme", "Zebra Distilling")
    assert result.status == "FAIL"
    assert result.score is not None
    assert result.score < 85


def test_brand_missing_expected_fails() -> None:
    result = compare_brand(None, "Acme")
    assert result.status == "FAIL"
    assert result.expected is None
    assert result.actual == "Acme"


def test_brand_missing_actual_fails() -> None:
    result = compare_brand("Acme", None)
    assert result.status == "FAIL"


def test_brand_empty_string_treated_as_missing() -> None:
    result = compare_brand("", "Acme")
    assert result.status == "FAIL"


def test_class_type_and_producer_use_fuzzy() -> None:
    assert compare_class_type("Straight Bourbon", "straight bourbon").status == "PASS"
    assert compare_producer("ACME DISTILLING CO", "Acme Distilling Co").status == "PASS"
