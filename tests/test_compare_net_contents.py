from app.comparison.fields import compare_net_contents


def test_750_ml_capital_l_vs_750ml_passes() -> None:
    """REVIEW #3: 750 mL vs 750ml passes."""
    result = compare_net_contents("750 mL", "750ml")
    assert result.status == "PASS"
    assert result.expected == "750 mL"
    assert result.actual == "750ml"


def test_ml_vs_cl_passes() -> None:
    result = compare_net_contents("750 ml", "75 cl")
    assert result.status == "PASS"


def test_ml_vs_liters_passes() -> None:
    result = compare_net_contents("750 ml", "0.75 L")
    assert result.status == "PASS"


def test_ml_vs_fl_oz_passes() -> None:
    result = compare_net_contents("750 ml", "25.4 fl oz")
    assert result.status == "PASS"


def test_different_volumes_fail() -> None:
    result = compare_net_contents("750 ml", "375 ml")
    assert result.status == "FAIL"


def test_bad_unit_fails() -> None:
    result = compare_net_contents("750 bottles", "750 ml")
    assert result.status == "FAIL"


def test_net_contents_missing_fails() -> None:
    result = compare_net_contents(None, "750 ml")
    assert result.status == "FAIL"
