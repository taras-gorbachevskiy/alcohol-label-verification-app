from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FieldStatus = Literal["PASS", "FAIL"]
Verdict = Literal["PASS", "NEEDS_REVIEW"]
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
