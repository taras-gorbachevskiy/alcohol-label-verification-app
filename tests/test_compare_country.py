from app.comparison.fields import compare_country


def test_usa_vs_united_states_passes() -> None:
    """REVIEW #4: USA vs United States passes."""
    result = compare_country("USA", "United States")
    assert result.status == "PASS"
    assert result.expected == "USA"
    assert result.actual == "United States"
    assert result.score is None


def test_same_unknown_country_passes() -> None:
    result = compare_country("Narnia", "Narnia")
    assert result.status == "PASS"


def test_different_countries_fail() -> None:
    result = compare_country("France", "Italy")
    assert result.status == "FAIL"


def test_unknown_vs_known_fails() -> None:
    result = compare_country("Narnia", "France")
    assert result.status == "FAIL"


def test_country_missing_fails() -> None:
    result = compare_country(None, "USA")
    assert result.status == "FAIL"
