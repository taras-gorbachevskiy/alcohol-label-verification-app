from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.verify import (
    VerifyApiError,
    http_error_handler,
    log_verify_completion,
    request_validation_error_handler,
    router as verify_router,
    start_verify_timer,
    unexpected_error_handler,
    verify_api_error_handler,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Alcohol Label Verification", version="0.1.0")
app.include_router(verify_router)
app.add_exception_handler(VerifyApiError, verify_api_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(  # type: ignore[arg-type]
    RequestValidationError,
    request_validation_error_handler,
)
app.add_exception_handler(StarletteHTTPException, http_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, unexpected_error_handler)


@app.middleware("http")
async def measure_verify_latency(request: Request, call_next):  # type: ignore[no-untyped-def]
    if request.url.path != "/verify":
        return await call_next(request)

    start_verify_timer(request)
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
