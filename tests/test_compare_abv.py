from app.comparison.fields import compare_abv


def test_abv_percent_vs_bare_number_passes() -> None:
    result = compare_abv("40%", "40")
    assert result.status == "PASS"
    assert result.score is None


def test_abv_noisy_alc_vol_proof_passes() -> None:
    """REVIEW #2: 45% vs 45% Alc./Vol. (90 Proof) passes; ignore proof."""
    result = compare_abv("45%", "45% Alc./Vol. (90 Proof)")
    assert result.status == "PASS"
    assert result.expected == "45%"
    assert result.actual == "45% Alc./Vol. (90 Proof)"


def test_brief_bare_45_vs_full_alc_vol_and_proof_passes() -> None:
    result = compare_abv("45", "45% Alc./Vol. (90 Proof)")
    assert result.status == "PASS"


def test_abv_within_tolerance_passes() -> None:
    result = compare_abv("40.0%", "40.02")
    assert result.status == "PASS"


def test_abv_different_values_fail() -> None:
    result = compare_abv("40", "41")
    assert result.status == "FAIL"


def test_abv_unparseable_fails() -> None:
    result = compare_abv("forty", "40")
    assert result.status == "FAIL"


def test_abv_missing_fails() -> None:
    result = compare_abv(None, "40%")
    assert result.status == "FAIL"
