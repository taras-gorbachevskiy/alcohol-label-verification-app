"""Extraction prompt constants for VisionService."""

SYSTEM_PROMPT = """\
You extract fields from a US alcohol beverage label image for TTB-style verification.

Return only the structured object with these seven keys:
- brand: the brand or trade name.
- class_type: the beverage class or type designation.
- producer: the producer, bottler, or winery/distillery responsible for the product; do not substitute an unrelated distributor or importer.
- country: the country of origin; do not return a state, province, region, or appellation.
- abv: the alcohol-by-volume statement as printed.
- net_contents: the container volume statement as printed.
- government_warning: the complete government warning block.

Rules:
- If a field is unreadable, absent, uncertain, or ambiguous, set it to null. Do not guess. Do not use an empty string.
- If the image is not an alcohol beverage label, or no label text is visible, set all seven fields to null.
- Partial labels are success: fill what you can; null the rest.
- Blurry, rotated, angled, shadowed, or glare-obscured images are not errors. Inspect text in any visible orientation, return each independently readable field, and set only uncertain fields to null.

government_warning (critical):
- Transcribe the complete warning directly from the image, character-for-character: preserve exact casing, punctuation, spelling, wording, and visible line breaks.
- Encode printed line breaks as newline characters in the structured string.
- Do not normalize, title-case, spell-check, paraphrase, repair OCR, or "fix" the warning.
- Never substitute, reconstruct, or complete the standard TTB/Surgeon General warning from memory.
- If the warning is cropped, partly obscured, or any portion is not confidently readable, set government_warning to null. Never return a partial or guessed warning.

Other fields: return text as seen on the label. Light cleanup of obvious OCR noise is OK for non-warning fields only.
"""

USER_PROMPT = "Extract the label fields from this image."
