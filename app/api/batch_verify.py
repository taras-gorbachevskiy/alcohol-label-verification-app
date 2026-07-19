from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from app.api.verify import (
    VerifyApiError,
    _guard_warning_extraction,
    _parse_application,
    _preprocess_upload,
    elapsed_verify_ms,
)
from app.comparison import compare_labels
from app.models import (
    BatchItemResult,
    BatchSummary,
    BatchVerificationResult,
    ErrorDetail,
    ErrorResponse,
    ExtractedLabel,
    VerificationApplicationData,
)
from app.rate_limit import client_identifier
from app.vision import AsyncVisionService, VisionUnavailableError

logger = logging.getLogger("uvicorn.error.app.verify")

MAX_BATCH_ITEMS = 5
BATCH_PROCESSING_DEADLINE_SECONDS = 4.8
_clock = time.perf_counter

router = APIRouter()


class AsyncVisionExtractor(Protocol):
    async def extract_preprocessed(self, jpeg_bytes: bytes) -> ExtractedLabel: ...


AsyncVisionServiceFactory = Callable[[], AsyncVisionExtractor]
_async_vision_service: AsyncVisionService | None = None


def _cached_async_vision_service() -> AsyncVisionService:
    global _async_vision_service
    if _async_vision_service is None:
        _async_vision_service = AsyncVisionService()
    return _async_vision_service


def get_async_vision_service_factory() -> AsyncVisionServiceFactory:
    return _cached_async_vision_service


async def close_async_vision_service() -> None:
    global _async_vision_service
    service = _async_vision_service
    _async_vision_service = None
    if service is not None:
        await service.aclose()


def _parse_manifest(applications: str) -> list[Any]:
    if not applications.strip():
        raise VerifyApiError(
            422,
            "EMPTY_BATCH_APPLICATIONS",
            "Provide application data for every label in the batch.",
            field="applications",
        )
    try:
        payload = json.loads(applications)
    except json.JSONDecodeError as exc:
        raise VerifyApiError(
            400,
            "INVALID_BATCH_JSON",
            "Batch application data must be a valid JSON array.",
            field="applications",
        ) from exc
    if not isinstance(payload, list):
        raise VerifyApiError(
            422,
            "INVALID_BATCH_APPLICATIONS",
            "Batch application data must be a JSON array.",
            field="applications",
        )
    if not payload:
        raise VerifyApiError(
            422,
            "EMPTY_BATCH",
            "Add at least one label to the batch.",
            field="applications",
        )
    if len(payload) > MAX_BATCH_ITEMS:
        raise VerifyApiError(
            422,
            "BATCH_SIZE_EXCEEDED",
            "Use no more than five labels in one batch.",
            field="applications",
        )
    return payload


def _filename(image: UploadFile, index: int) -> str:
    name = (image.filename or "").strip()
    return name[:255] if name else f"Label {index + 1}"


def _prepare_item(
    image: UploadFile,
    application_payload: Any,
) -> tuple[VerificationApplicationData, bytes] | VerifyApiError:
    try:
        application = _parse_application(json.dumps(application_payload))
        jpeg_bytes = _preprocess_upload(image)
        return application, jpeg_bytes
    except VerifyApiError as exc:
        return exc
    except Exception as exc:
        logger.error("batch item preparation failure error_type=%s", type(exc).__name__)
        return VerifyApiError(
            400,
            "INVALID_IMAGE",
            "The image could not be read. Choose a valid JPEG, PNG, or WebP image.",
            field="image",
        )


def _prepare_indexed_item(
    index: int,
    image: UploadFile,
    application_payload: Any,
) -> tuple[VerificationApplicationData, bytes] | VerifyApiError:
    """Add an exact batch item path without changing the tested worker seam."""

    prepared = _prepare_item(image, application_payload)
    if not isinstance(prepared, VerifyApiError):
        return prepared
    field = prepared.field
    if field == "image":
        field = f"images[{index}]"
    elif field == "application":
        field = f"applications[{index}]"
    elif field and field.startswith("application."):
        field = f"applications[{index}].{field.removeprefix('application.')}"
    return VerifyApiError(
        prepared.status_code,
        prepared.code,
        prepared.message,
        field=field,
        headers=prepared.headers,
    )


def _unavailable_item(
    index: int,
    filename: str,
    error: VerifyApiError | None = None,
) -> BatchItemResult:
    detail = ErrorDetail(
        code=error.code if error else "VERIFICATION_UNAVAILABLE",
        message=(
            error.message
            if error
            else "We could not verify this label. Check it and try again."
        ),
        field=error.field if error else None,
    )
    return BatchItemResult(
        index=index,
        filename=filename,
        status="UNABLE_TO_VERIFY",
        error=detail,
    )


async def _verify_prepared_item(
    *,
    index: int,
    filename: str,
    application: VerificationApplicationData,
    jpeg_bytes: bytes,
    service: AsyncVisionExtractor,
    timeout: float,
    lease: Any,
) -> BatchItemResult:
    started_at = _clock()
    try:
        if timeout <= 0:
            raise TimeoutError
        extracted = await asyncio.wait_for(
            service.extract_preprocessed(jpeg_bytes),
            timeout=timeout,
        )
        extracted = _guard_warning_extraction(application, extracted)
        result = compare_labels(application.to_application_data(), extracted)
        result.latency_ms = round(max(0.0, (_clock() - started_at) * 1_000), 2)
        return BatchItemResult(
            index=index,
            filename=filename,
            status=result.verdict,
            result=result,
        )
    except asyncio.CancelledError:
        raise
    except (TimeoutError, asyncio.TimeoutError, VisionUnavailableError):
        return _unavailable_item(index, filename)
    except Exception as exc:
        logger.error(
            "batch item verification failure index=%d error_type=%s",
            index,
            type(exc).__name__,
        )
        return _unavailable_item(index, filename)
    finally:
        lease.release()


def _release_deferred_preparation(
    task: asyncio.Task[tuple[VerificationApplicationData, bytes] | VerifyApiError],
    *,
    index: int,
    deferred_indexes: set[int],
    lease: Any,
) -> None:
    """Release a slot only after an abandoned preprocessing worker is done."""

    if index not in deferred_indexes:
        return
    try:
        task.result()
    except BaseException:
        # The item has already been reported as unavailable. Consume any task
        # exception without exposing item data or producing an unhandled-task log.
        pass
    finally:
        lease.release()


def _batch_result(
    request: Request,
    items: list[BatchItemResult],
) -> BatchVerificationResult:
    passed = sum(item.status == "PASS" for item in items)
    needs_review = sum(item.status == "NEEDS_REVIEW" for item in items)
    unavailable = sum(item.status == "UNABLE_TO_VERIFY" for item in items)
    latency_ms = elapsed_verify_ms(request)
    result = BatchVerificationResult(
        summary=BatchSummary(
            passed=passed,
            needs_review=needs_review,
            unable_to_verify=unavailable,
            total=len(items),
        ),
        items=items,
        latency_ms=latency_ms,
    )
    request.state.verify_latency_ms = latency_ms
    request.state.batch_summary = result.summary
    return result


@router.post(
    "/verify/batch",
    response_model=BatchVerificationResult,
    responses={
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": BatchVerificationResult | ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {"model": BatchVerificationResult},
    },
)
async def verify_batch(
    request: Request,
    images: Annotated[
        list[UploadFile],
        File(description="One to five ordered JPEG, PNG, or WebP label images."),
    ],
    applications: Annotated[
        str,
        Form(description="Ordered JSON array of one to five application objects."),
    ],
    vision_service_factory: Annotated[
        AsyncVisionServiceFactory,
        Depends(get_async_vision_service_factory),
    ],
) -> BatchVerificationResult | JSONResponse:
    manifest = _parse_manifest(applications)
    if len(images) != len(manifest):
        raise VerifyApiError(
            422,
            "BATCH_PAIR_COUNT_MISMATCH",
            "Provide exactly one image for each application in the batch.",
            field=None,
        )

    limiter = request.app.state.verify_limiter
    client_id = getattr(request.state, "client_id", client_identifier(request))
    # Middleware has already charged one attempt before multipart parsing. A
    # structurally valid batch pays only the remaining per-label cost here.
    remaining_client_cost = len(images) - 1
    if remaining_client_cost:
        client_decision = limiter.check_client(
            client_id,
            cost=remaining_client_cost,
        )
        if not client_decision.allowed:
            request.state.rate_limit_scope = client_decision.scope
            raise VerifyApiError(
                429,
                client_decision.code,
                "Too many labels have been checked. Please wait and try again.",
                headers={"Retry-After": str(client_decision.retry_after)},
            )

    decision, leases = limiter.acquire_processing_slots(len(images))
    if not decision.allowed:
        request.state.rate_limit_scope = decision.scope
        raise VerifyApiError(
            429,
            decision.code,
            "The checker is busy. Please wait a few seconds and try again.",
            headers={"Retry-After": str(decision.retry_after)},
        )

    deadline = _clock() + BATCH_PROCESSING_DEADLINE_SECONDS
    filenames = [_filename(image, index) for index, image in enumerate(images)]
    item_results: list[BatchItemResult | None] = [None] * len(images)
    valid: list[tuple[int, VerificationApplicationData, bytes]] = []
    preparation_tasks: list[
        asyncio.Task[tuple[VerificationApplicationData, bytes] | VerifyApiError]
    ] = []
    deferred_preparation_indexes: set[int] = set()

    try:
        preparation_tasks = [
            asyncio.create_task(
                asyncio.to_thread(_prepare_indexed_item, index, image, application)
            )
            for index, (image, application) in enumerate(
                zip(images, manifest, strict=True)
            )
        ]
        for index, task in enumerate(preparation_tasks):
            task.add_done_callback(
                lambda completed, item_index=index: _release_deferred_preparation(
                    completed,
                    index=item_index,
                    deferred_indexes=deferred_preparation_indexes,
                    lease=leases[item_index],
                )
            )
        _done, pending = await asyncio.wait(
            preparation_tasks,
            timeout=max(0.0, deadline - _clock()),
        )
        if pending:
            request.state.batch_deadline_exceeded = True

        for index, task in enumerate(preparation_tasks):
            if task in pending:
                deferred_preparation_indexes.add(index)
                # The callback may already have run between asyncio.wait()
                # returning and ownership being marked as deferred.
                if task.done():
                    leases[index].release()
                item_results[index] = _unavailable_item(index, filenames[index])
                continue
            item = task.result()
            if isinstance(item, VerifyApiError):
                item_results[index] = _unavailable_item(
                    index,
                    filenames[index],
                    item,
                )
                leases[index].release()
            else:
                application, jpeg_bytes = item
                valid.append((index, application, jpeg_bytes))

        if not valid:
            result = _batch_result(
                request,
                [item for item in item_results if item is not None],
            )
            status_code = (
                503
                if getattr(request.state, "batch_deadline_exceeded", False)
                else 422
            )
            return JSONResponse(status_code=status_code, content=result.model_dump())

        remaining = deadline - _clock()
        if remaining <= 0:
            for index, _application, _jpeg_bytes in valid:
                item_results[index] = _unavailable_item(index, filenames[index])
                leases[index].release()
            request.state.batch_deadline_exceeded = True
            result = _batch_result(
                request,
                [item for item in item_results if item is not None],
            )
            return JSONResponse(status_code=503, content=result.model_dump())

        try:
            service = vision_service_factory()
        except Exception as exc:
            logger.error(
                "batch vision service failure error_type=%s",
                type(exc).__name__,
            )
            for index, _application, _jpeg_bytes in valid:
                item_results[index] = _unavailable_item(index, filenames[index])
                leases[index].release()
            result = _batch_result(
                request,
                [item for item in item_results if item is not None],
            )
            return JSONResponse(status_code=503, content=result.model_dump())

        global_decision = limiter.charge_global(len(valid))
        if not global_decision.allowed:
            request.state.rate_limit_scope = global_decision.scope
            raise VerifyApiError(
                429,
                global_decision.code,
                "Too many labels have been checked. Please wait and try again.",
                headers={"Retry-After": str(global_decision.retry_after)},
            )

        verified = await asyncio.gather(
            *(
                _verify_prepared_item(
                    index=index,
                    filename=filenames[index],
                    application=application,
                    jpeg_bytes=jpeg_bytes,
                    service=service,
                    timeout=max(0.0, deadline - _clock()),
                    lease=leases[index],
                )
                for index, application, jpeg_bytes in valid
            )
        )
        for item in verified:
            item_results[item.index] = item

        ordered_items = [item for item in item_results if item is not None]
        result = _batch_result(request, ordered_items)
        if result.summary.passed + result.summary.needs_review == 0:
            request.state.batch_deadline_exceeded = _clock() >= deadline
            return JSONResponse(status_code=503, content=result.model_dump())
        return result
    finally:
        # A cancelled request may leave preprocessing threads running. Hand
        # those leases to their task callbacks; all other paths are safe to
        # release immediately (leases are idempotent).
        for index, task in enumerate(preparation_tasks):
            if not task.done():
                deferred_preparation_indexes.add(index)
                if task.done():
                    leases[index].release()
        for index, lease in enumerate(leases):
            if index not in deferred_preparation_indexes:
                lease.release()
