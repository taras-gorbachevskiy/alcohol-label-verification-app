from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.body_limit import REQUEST_TOO_LARGE_MESSAGE
from app.comparison import compare_labels
from app.models import (
    ErrorDetail,
    ErrorResponse,
    ExtractedLabel,
    VerificationApplicationData,
    VerificationResult,
)
from app.vision import VisionService, VisionUnavailableError
from app.vision.preprocess import (
    MAX_INPUT_BYTES,
    SUPPORTED_CONTENT_TYPES,
    ImagePreprocessError,
    preprocess_image,
)

# Use Uvicorn's configured error hierarchy so INFO completion records are
# visible in local, Railway, and other Uvicorn-backed deployments.
logger = logging.getLogger("uvicorn.error.app.verify")

LATENCY_BUDGET_MS = 5_000.0
_clock = time.perf_counter

router = APIRouter()


class VisionExtractor(Protocol):
    def extract_preprocessed(self, jpeg_bytes: bytes) -> ExtractedLabel: ...


VisionServiceFactory = Callable[[], VisionExtractor]


@lru_cache(maxsize=1)
def _cached_vision_service() -> VisionService:
    return VisionService()


def get_vision_service_factory() -> VisionServiceFactory:
    """Inject a lazy factory so invalid requests do not require API setup."""
    return _cached_vision_service


class VerifyApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        field: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field = field
        self.headers = headers


def start_verify_timer(request: Request) -> None:
    request.state.verify_started_at = _clock()


def elapsed_verify_ms(request: Request) -> float:
    started_at = getattr(request.state, "verify_started_at", None)
    if started_at is None:
        started_at = _clock()
        request.state.verify_started_at = started_at
    return round(max(0.0, (_clock() - started_at) * 1_000), 2)


def log_verify_completion(request: Request, status_code: int) -> None:
    latency_ms = getattr(request.state, "verify_latency_ms", None)
    if latency_ms is None:
        latency_ms = elapsed_verify_ms(request)
        request.state.verify_latency_ms = latency_ms

    within_budget = latency_ms < LATENCY_BUDGET_MS
    level = logging.INFO if within_budget else logging.WARNING
    logger.log(
        level,
        "verify_complete status_code=%d latency_ms=%.2f within_budget=%s "
        "verdict=%s error_code=%s rate_limit_scope=%s",
        status_code,
        latency_ms,
        within_budget,
        getattr(request.state, "verify_verdict", "-"),
        getattr(request.state, "verify_error_code", "-"),
        getattr(request.state, "rate_limit_scope", "-"),
    )


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    field: str | None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request.state.verify_error_code = code
    payload = ErrorResponse(
        error=ErrorDetail(code=code, message=message, field=field)
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(),
        headers=headers,
    )


async def verify_api_error_handler(
    request: Request,
    exc: VerifyApiError,
) -> JSONResponse:
    return error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        field=exc.field,
        headers=exc.headers,
    )


async def request_validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    fields = {
        str(error["loc"][-1])
        for error in exc.errors()
        if error.get("loc")
    }
    if fields == {"image"}:
        message = "Choose an image before submitting."
        field = "image"
    elif fields == {"application"}:
        message = "Provide application data before submitting."
        field = "application"
    else:
        message = "Choose an image and provide application data before submitting."
        field = None
    return error_response(
        request,
        status_code=422,
        code="MISSING_SUBMISSION",
        message=message,
        field=field,
    )


async def http_error_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    if request.url.path == "/verify" and exc.status_code == 413:
        return error_response(
            request,
            status_code=413,
            code="REQUEST_TOO_LARGE",
            message=REQUEST_TOO_LARGE_MESSAGE,
            field=None,
        )

    content_type = request.headers.get("content-type", "").lower()
    is_multipart_parse_error = (
        request.url.path == "/verify"
        and exc.status_code == 400
        and content_type.startswith("multipart/form-data")
    )
    if not is_multipart_parse_error:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )
    return error_response(
        request,
        status_code=400,
        code="INVALID_MULTIPART",
        message="The upload could not be read. Submit an image and application data.",
        field=None,
    )


async def unexpected_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    if request.url.path == "/verify":
        logger.error(
            "unexpected verify failure error_type=%s",
            type(exc).__name__,
        )
        return error_response(
            request,
            status_code=500,
            code="VERIFICATION_UNAVAILABLE",
            message=(
                "We could not verify this label right now. "
                "Please try again or contact support."
            ),
            field=None,
        )
    logger.error("unexpected application failure error_type=%s", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "Internal error."}},
    )


def _parse_application(application: str) -> VerificationApplicationData:
    if not application.strip():
        raise VerifyApiError(
            422,
            "EMPTY_APPLICATION",
            "Application data cannot be empty.",
            field="application",
        )

    try:
        payload = json.loads(application)
    except json.JSONDecodeError as exc:
        raise VerifyApiError(
            400,
            "INVALID_APPLICATION_JSON",
            "Application data must be valid JSON.",
            field="application",
        ) from exc

    if not isinstance(payload, dict):
        raise VerifyApiError(
            422,
            "INVALID_APPLICATION",
            "Application data must be a JSON object containing all required fields.",
            field="application",
        )

    try:
        return VerificationApplicationData.model_validate(payload)
    except ValidationError as exc:
        first_error = exc.errors()[0] if exc.errors() else {}
        location = first_error.get("loc", ())
        field_name = str(location[0]) if location else None
        field = f"application.{field_name}" if field_name else "application"
        if first_error.get("type") == "string_too_long":
            raise VerifyApiError(
                422,
                "APPLICATION_FIELD_TOO_LONG",
                "Use 2,000 characters or fewer for each application field.",
                field=field,
            ) from exc
        raise VerifyApiError(
            422,
            "INVALID_APPLICATION",
            "Provide nonblank text values for exactly the seven required fields.",
            field=field,
        ) from exc


def _preprocess_upload(image: UploadFile) -> bytes:
    content_type = (image.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in SUPPORTED_CONTENT_TYPES:
        raise VerifyApiError(
            415,
            "UNSUPPORTED_IMAGE_TYPE",
            "Upload a JPEG, PNG, or WebP image.",
            field="image",
        )

    image_bytes = image.file.read(MAX_INPUT_BYTES + 1)
    if not image_bytes:
        raise VerifyApiError(
            400,
            "EMPTY_IMAGE",
            "The uploaded image is empty. Choose a JPEG, PNG, or WebP image.",
            field="image",
        )
    if len(image_bytes) > MAX_INPUT_BYTES:
        raise VerifyApiError(
            413,
            "IMAGE_TOO_LARGE",
            "The image is too large. Upload an image no larger than 20 MiB.",
            field="image",
        )

    try:
        return preprocess_image(image_bytes, content_type=content_type)
    except ImagePreprocessError as exc:
        if exc.reason == "image_too_large":
            raise VerifyApiError(
                413,
                "IMAGE_TOO_LARGE",
                "The image dimensions are too large.",
                field="image",
            ) from exc
        if exc.reason == "unsupported_image_type":
            raise VerifyApiError(
                415,
                "UNSUPPORTED_IMAGE_TYPE",
                "Upload a JPEG, PNG, or WebP image.",
                field="image",
            ) from exc
        if exc.reason == "image_type_mismatch":
            raise VerifyApiError(
                400,
                "IMAGE_TYPE_MISMATCH",
                "The image content does not match its declared file type.",
                field="image",
            ) from exc
        raise VerifyApiError(
            400,
            "INVALID_IMAGE",
            "The image could not be read. Choose a valid JPEG, PNG, or WebP image.",
            field="image",
        ) from exc


@router.post(
    "/verify",
    response_model=VerificationResult,
    responses={
        400: {"model": ErrorResponse},
        413: {
            "model": ErrorResponse,
            "description": "Multipart request exceeds the 21 MiB total limit.",
        },
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {
            "model": ErrorResponse,
            "description": "Vision provider or extraction is temporarily unavailable.",
        },
    },
)
def verify_label(
    request: Request,
    image: Annotated[
        UploadFile,
        File(
            description=(
                "JPEG, PNG, or WebP label image, maximum 20 MiB. "
                "The complete multipart request is limited to 21 MiB."
            )
        ),
    ],
    application: Annotated[
        str,
        Form(
            description=(
                "JSON object with exactly seven required string fields; "
                "maximum 2,000 characters per field."
            )
        ),
    ],
    vision_service_factory: Annotated[
        VisionServiceFactory,
        Depends(get_vision_service_factory),
    ],
) -> VerificationResult:
    application_data = _parse_application(application)
    jpeg_bytes = _preprocess_upload(image)

    limiter = request.app.state.verify_limiter
    decision, lease = limiter.acquire_verification()
    if not decision.allowed:
        request.state.rate_limit_scope = decision.scope
        message = (
            "The checker is busy. Please wait a few seconds and try again."
            if decision.code == "VERIFICATION_BUSY"
            else "Too many labels have been checked. Please wait and try again."
        )
        raise VerifyApiError(
            429,
            decision.code,
            message,
            headers={"Retry-After": str(decision.retry_after)},
        )
    assert lease is not None

    try:
        extracted = vision_service_factory().extract_preprocessed(jpeg_bytes)
        result = compare_labels(application_data.to_application_data(), extracted)
    except VisionUnavailableError as exc:
        logger.warning(
            "vision unavailable error_type=%s",
            type(exc).__name__,
        )
        raise VerifyApiError(
            503,
            "VERIFICATION_UNAVAILABLE",
            (
                "We could not verify this label right now. "
                "Your information is still here. Please try again."
            ),
        ) from exc
    except Exception as exc:
        logger.error(
            "verification service failure error_type=%s",
            type(exc).__name__,
        )
        raise VerifyApiError(
            500,
            "VERIFICATION_UNAVAILABLE",
            (
                "We could not verify this label right now. "
                "Please try again or contact support."
            ),
        ) from exc
    finally:
        lease.release()

    latency_ms = elapsed_verify_ms(request)
    result.latency_ms = latency_ms
    request.state.verify_latency_ms = latency_ms
    request.state.verify_verdict = result.verdict
    return result
