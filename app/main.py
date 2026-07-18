from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.batch_verify import (
    close_async_vision_service,
    router as batch_verify_router,
)
from app.api.verify import (
    VerifyApiError,
    error_response,
    http_error_handler,
    log_verify_completion,
    request_validation_error_handler,
    router as verify_router,
    start_verify_timer,
    unexpected_error_handler,
    verify_api_error_handler,
)
from app.body_limit import VerifyBodyLimitMiddleware
from app.rate_limit import RateLimitSettings, VerifyRateLimiter, client_identifier

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
    yield
    await close_async_vision_service()


app = FastAPI(
    title="Alcohol Label Verification",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.verify_limiter = VerifyRateLimiter(RateLimitSettings.from_env())
app.include_router(verify_router)
app.include_router(batch_verify_router)
app.add_exception_handler(VerifyApiError, verify_api_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(  # type: ignore[arg-type]
    RequestValidationError,
    request_validation_error_handler,
)
app.add_exception_handler(StarletteHTTPException, http_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, unexpected_error_handler)
app.add_middleware(VerifyBodyLimitMiddleware)


@app.middleware("http")
async def measure_verify_latency(request: Request, call_next):  # type: ignore[no-untyped-def]
    if (
        request.url.path not in {"/verify", "/verify/batch"}
        or request.method != "POST"
    ):
        return await call_next(request)

    start_verify_timer(request)
    limiter = request.app.state.verify_limiter
    request.state.client_id = client_identifier(request)
    # Record one attempt before multipart parsing for both endpoints. Batch
    # verification charges any remaining per-label cost after its manifest is
    # structurally valid, so malformed and oversized batches cannot bypass the
    # client abuse limit.
    decision = limiter.check_client(request.state.client_id)
    if not decision.allowed:
        request.state.rate_limit_scope = decision.scope
        response = error_response(
            request,
            status_code=429,
            code=decision.code,
            message=(
                "Too many labels have been checked. Please wait and try again."
            ),
            field=None,
            headers={"Retry-After": str(decision.retry_after)},
        )
        log_verify_completion(request, response.status_code)
        return response

    try:
        response = await call_next(request)
    except Exception:
        # The catch-all exception handler runs outside user middleware, so log
        # the completion record here before allowing it to shape the response.
        request.state.verify_error_code = "VERIFICATION_UNAVAILABLE"
        log_verify_completion(request, 500)
        raise
    log_verify_completion(request, response.status_code)
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# Mount after API routes so /health is not shadowed.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
