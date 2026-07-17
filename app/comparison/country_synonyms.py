"""Map country name variants to a canonical key."""

_SYNONYMS: dict[str, str] = {
    "us": "US",
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "united states": "US",
    "united states of america": "US",
    "uk": "UK",
    "u.k.": "UK",
    "united kingdom": "UK",
    "great britain": "UK",
    "france": "FR",
    "italy": "IT",
    "spain": "ES",
    "germany": "DE",
    "mexico": "MX",
    "canada": "CA",
    "chile": "CL",
    "argentina": "AR",
    "australia": "AU",
    "portugal": "PT",
    "ireland": "IE",
}


def canonicalize_country(value: str) -> str:
    key = " ".join(value.strip().casefold().split())
    return _SYNONYMS.get(key, key)
