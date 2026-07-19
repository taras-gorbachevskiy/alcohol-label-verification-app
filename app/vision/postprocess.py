"""Post-process extracted label fields before comparison."""

from __future__ import annotations

from app.models import ExtractedLabel


def normalize_extracted_label(label: ExtractedLabel) -> ExtractedLabel:
    """Treat empty strings as missing and remove OCR layout line wrapping."""

    data = label.model_dump()
    for key, value in data.items():
        if isinstance(value, str) and not value.strip():
            data[key] = None
    warning = data.get("government_warning")
    if isinstance(warning, str):
        # A printed line wrap is page layout, not a character in the warning.
        # Preserve all other whitespace so exact comparison remains strict.
        data["government_warning"] = (
            warning.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        )
    return ExtractedLabel(**data)


def guard_warning_extraction(
    expected_warning: str,
    extracted: ExtractedLabel,
) -> ExtractedLabel:
    """Degrade altered warning OCR to missing instead of exposing guessed text."""

    warning = extracted.government_warning
    if warning is None or warning == expected_warning:
        return extracted
    return extracted.model_copy(update={"government_warning": None})
