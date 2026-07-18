from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FieldStatus = Literal["PASS", "FAIL"]
Verdict = Literal["PASS", "NEEDS_REVIEW"]
BatchItemStatus = Literal["PASS", "NEEDS_REVIEW", "UNABLE_TO_VERIFY"]
MAX_APPLICATION_FIELD_CHARS = 2_000


class ApplicationData(BaseModel):
    brand: str | None = None
    class_type: str | None = None
    producer: str | None = None
    country: str | None = None
    abv: str | None = None
    net_contents: str | None = None
    government_warning: str | None = None


class VerificationApplicationData(BaseModel):
    """Strict application payload accepted by the verification endpoint."""

    model_config = ConfigDict(extra="forbid", strict=True)

    brand: str = Field(max_length=MAX_APPLICATION_FIELD_CHARS)
    class_type: str = Field(max_length=MAX_APPLICATION_FIELD_CHARS)
    producer: str = Field(max_length=MAX_APPLICATION_FIELD_CHARS)
    country: str = Field(max_length=MAX_APPLICATION_FIELD_CHARS)
    abv: str = Field(max_length=MAX_APPLICATION_FIELD_CHARS)
    net_contents: str = Field(max_length=MAX_APPLICATION_FIELD_CHARS)
    government_warning: str = Field(max_length=MAX_APPLICATION_FIELD_CHARS)

    @field_validator("*")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    def to_application_data(self) -> ApplicationData:
        return ApplicationData(**self.model_dump())


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
    latency_ms: float = Field(ge=0)


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class BatchSummary(BaseModel):
    passed: int = Field(ge=0)
    needs_review: int = Field(ge=0)
    unable_to_verify: int = Field(ge=0)
    total: int = Field(ge=1, le=5)

    @model_validator(mode="after")
    def require_complete_count(self) -> "BatchSummary":
        if self.passed + self.needs_review + self.unable_to_verify != self.total:
            raise ValueError("batch summary counts must add up to total")
        return self


class BatchItemResult(BaseModel):
    index: int = Field(ge=0, le=4)
    filename: str
    status: BatchItemStatus
    result: VerificationResult | None = None
    error: ErrorDetail | None = None

    @model_validator(mode="after")
    def require_status_payload(self) -> "BatchItemResult":
        if self.status == "UNABLE_TO_VERIFY":
            if self.result is not None or self.error is None:
                raise ValueError("unavailable batch items require only an error")
            return self
        if self.result is None or self.error is not None:
            raise ValueError("verified batch items require only a result")
        if self.result.verdict != self.status:
            raise ValueError("batch item status must match result verdict")
        return self


class BatchVerificationResult(BaseModel):
    summary: BatchSummary
    items: list[BatchItemResult] = Field(min_length=1, max_length=5)
    latency_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def require_consistent_items(self) -> "BatchVerificationResult":
        if len(self.items) != self.summary.total:
            raise ValueError("batch item count must match summary total")
        expected_indexes = list(range(len(self.items)))
        if [item.index for item in self.items] != expected_indexes:
            raise ValueError("batch items must be ordered by contiguous index")
        counts = {
            "PASS": self.summary.passed,
            "NEEDS_REVIEW": self.summary.needs_review,
            "UNABLE_TO_VERIFY": self.summary.unable_to_verify,
        }
        for status, expected in counts.items():
            if sum(item.status == status for item in self.items) != expected:
                raise ValueError("batch summary must match item statuses")
        return self
