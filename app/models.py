from typing import Literal

from pydantic import BaseModel, Field

FieldStatus = Literal["PASS", "FAIL"]
Verdict = Literal["PASS", "NEEDS_REVIEW"]


class ApplicationData(BaseModel):
    brand: str | None = None
    class_type: str | None = None
    producer: str | None = None
    country: str | None = None
    abv: str | None = None
    net_contents: str | None = None
    government_warning: str | None = None


class ExtractedLabel(BaseModel):
    brand: str | None = None
    class_type: str | None = None
    producer: str | None = None
    country: str | None = None
    abv: str | None = None
    net_contents: str | None = None
    government_warning: str | None = None


class FieldResult(BaseModel):
    field: str
    status: FieldStatus
    expected: str | None = None
    actual: str | None = None
    score: float | None = None
    detail: str | None = None


class VerificationResult(BaseModel):
    verdict: Verdict
    fields: list[FieldResult] = Field(default_factory=list)
