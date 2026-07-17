"""Shared government-warning fixtures for Phase 1 comparison tests."""

# Exact TTB-style all-caps warning used as the application (expected) value.
ALL_CAPS_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)

TITLE_CASE_WARNING = (
    "Government Warning: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)

MISSING_COLON_WARNING = ALL_CAPS_WARNING.replace("GOVERNMENT WARNING:", "GOVERNMENT WARNING", 1)

MISREAD_WARNING = "GOVERNMENT WARNING: OCR GARBLED TEXT"
