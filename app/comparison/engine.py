from app.comparison.fields import (
    compare_abv,
    compare_brand,
    compare_class_type,
    compare_country,
    compare_government_warning,
    compare_net_contents,
    compare_producer,
)
from app.models import ApplicationData, ExtractedLabel, VerificationResult


def compare_labels(
    application: ApplicationData,
    extracted: ExtractedLabel,
) -> VerificationResult:
    fields = [
        compare_brand(application.brand, extracted.brand),
        compare_class_type(application.class_type, extracted.class_type),
        compare_producer(application.producer, extracted.producer),
        compare_country(application.country, extracted.country),
        compare_abv(application.abv, extracted.abv),
        compare_net_contents(application.net_contents, extracted.net_contents),
        compare_government_warning(
            application.government_warning,
            extracted.government_warning,
        ),
    ]
    verdict = "NEEDS_REVIEW" if any(f.status == "FAIL" for f in fields) else "PASS"
    # HTTP orchestration replaces this placeholder with total request latency.
    return VerificationResult(verdict=verdict, fields=fields, latency_ms=0.0)
