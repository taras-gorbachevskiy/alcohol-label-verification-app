import re

FUZZY_THRESHOLD = 85
ABV_TOLERANCE = 0.05
NET_CONTENTS_RELATIVE_TOLERANCE = 0.005

_WHITESPACE_RE = re.compile(r"\s+")
_ABV_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%?")
_NET_CONTENTS_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(fl\s*\.?oz|floz|oz|ml|cl|l)\s*$",
    re.IGNORECASE,
)

# Milliliters per unit
_UNIT_TO_ML = {
    "ml": 1.0,
    "cl": 10.0,
    "l": 1000.0,
    "floz": 29.5735295625,
    "oz": 29.5735295625,
}


def is_missing(value: str | None) -> bool:
    return value is None or value.strip() == ""


def prep_fuzzy(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value.strip()).casefold()


def prep_warning(value: str) -> str:
    """Whitespace-only normalize; preserve case for exact comparison."""
    return _WHITESPACE_RE.sub(" ", value.strip())


def parse_abv(value: str) -> float | None:
    """Extract the first percentage-like number; ignore proof parentheticals."""
    match = _ABV_RE.search(value)
    if match is None:
        return None
    # Reject pure words: require a digit somewhere (already in regex).
    # If the string has no digit at all, regex fails. "forty" → None.
    if not re.search(r"\d", value):
        return None
    # Prefer a match that includes % when present, else first number.
    percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", value)
    if percent_match:
        return float(percent_match.group(1))
    return float(match.group(1))


def parse_net_contents_ml(value: str) -> float | None:
    match = _NET_CONTENTS_RE.match(value.strip())
    if match is None:
        return None
    amount = float(match.group(1))
    unit_raw = match.group(2).lower().replace(" ", "").replace(".", "")
    if unit_raw in ("floz", "oz"):
        unit = "floz"
    else:
        unit = unit_raw
    factor = _UNIT_TO_ML.get(unit)
    if factor is None:
        return None
    return amount * factor
