"""Bound verification request bodies before multipart parsing exhausts resources."""

from __future__ import annotations

from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.models import ErrorDetail, ErrorResponse
from app.vision.preprocess import MAX_INPUT_BYTES

MULTIPART_ALLOWANCE_BYTES = 1024 * 1024
MAX_VERIFY_REQUEST_BYTES = MAX_INPUT_BYTES + MULTIPART_ALLOWANCE_BYTES
MAX_BATCH_ITEMS = 5
MAX_BATCH_REQUEST_BYTES = (
    MAX_BATCH_ITEMS * MAX_INPUT_BYTES + MULTIPART_ALLOWANCE_BYTES
)

REQUEST_TOO_LARGE_MESSAGE = (
    "The upload is too large. Choose a label photo smaller than 20 MB."
)
BATCH_REQUEST_TOO_LARGE_MESSAGE = (
    "The batch is too large. Use no more than five label photos under 20 MB each."
)
INVALID_CONTENT_LENGTH_MESSAGE = (
    "The upload could not be read. Submit a label photo and all seven items again."
)


class VerifyBodyTooLarge(StarletteHTTPException):
    """Signal a streamed body that crossed the hard request limit."""

    def __init__(self) -> None:
        super().__init__(status_code=413, detail=REQUEST_TOO_LARGE_MESSAGE)


def _content_length(headers: list[tuple[bytes, bytes]]) -> int | None:
    values = [value for name, value in headers if name.lower() == b"content-length"]
    if not values:
        return None
    if len(values) != 1:
        raise ValueError("multiple content-length headers")
    value = values[0]
    if not value or not value.isdigit():
        raise ValueError("invalid content-length header")
    return int(value)


async def _send_error(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    status_code: int,
    code: str,
    message: str,
) -> None:
    state = scope.setdefault("state", {})
    state["verify_error_code"] = code
    payload = ErrorResponse(
        error=ErrorDetail(code=code, message=message, field=None)
    )
    response = JSONResponse(status_code=status_code, content=payload.model_dump())
    await response(scope, receive, send)


class VerifyBodyLimitMiddleware:
    """Reject oversized verifier bodies, including streams without a length."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int = MAX_VERIFY_REQUEST_BYTES,
        batch_max_bytes: int = MAX_BATCH_REQUEST_BYTES,
    ) -> None:
        if max_bytes <= 0 or batch_max_bytes <= 0:
            raise ValueError("request body limits must be positive")
        self.app = app
        self.max_bytes = max_bytes
        self.batch_max_bytes = batch_max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path")
        is_verify_request = (
            scope["type"] == "http"
            and path in {"/verify", "/verify/batch"}
            and scope.get("method") == "POST"
        )
        if not is_verify_request:
            await self.app(scope, receive, send)
            return

        limit = self.batch_max_bytes if path == "/verify/batch" else self.max_bytes
        too_large_message = (
            BATCH_REQUEST_TOO_LARGE_MESSAGE
            if path == "/verify/batch"
            else REQUEST_TOO_LARGE_MESSAGE
        )

        headers = scope.get("headers", [])
        try:
            declared_length = _content_length(headers)
        except ValueError:
            await _send_error(
                scope,
                receive,
                send,
                status_code=400,
                code="INVALID_MULTIPART",
                message=INVALID_CONTENT_LENGTH_MESSAGE,
            )
            return

        if declared_length is not None and declared_length > limit:
            await _send_error(
                scope,
                receive,
                send,
                status_code=413,
                code="REQUEST_TOO_LARGE",
                message=too_large_message,
            )
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise VerifyBodyTooLarge()
            return message

        await self.app(scope, limited_receive, send)
