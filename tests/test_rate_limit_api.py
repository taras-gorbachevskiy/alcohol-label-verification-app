from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.verify import get_vision_service_factory
from app.main import app
from app.models import ExtractedLabel
from app.rate_limit import RateLimitSettings, VerifyRateLimiter
from tests.warning_fixtures import ALL_CAPS_WARNING


class MutableClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _settings(**updates: int) -> RateLimitSettings:
    values = {
        "per_minute": 5,
        "per_hour": 30,
        "global_per_hour": 100,
        "max_concurrent": 2,
    }
    values.update(updates)
    return RateLimitSettings(**values)


def _application() -> dict[str, str]:
    return {
        "brand": "RIVERBEND RESERVE",
        "class_type": "Cabernet Sauvignon",
        "producer": "Riverbend Winery",
        "country": "USA",
        "abv": "13.5%",
        "net_contents": "750 mL",
        "government_warning": ALL_CAPS_WARNING,
    }


def _extracted() -> ExtractedLabel:
    return ExtractedLabel(
        brand="Riverbend Reserve",
        class_type="Cabernet Sauvignon",
        producer="Riverbend Winery",
        country="United States",
        abv="13.5% alc/vol",
        net_contents="750ml",
        government_warning=ALL_CAPS_WARNING,
    )


def _image_bytes() -> bytes:
    image = Image.new("RGB", (32, 24), (210, 190, 170))
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _post(
    client: TestClient,
    *,
    ip: str = "203.0.113.1",
    image_bytes: bytes | None = None,
    content_type: str = "image/jpeg",
):  # type: ignore[no-untyped-def]
    image = _image_bytes() if image_bytes is None else image_bytes
    return client.post(
        "/verify",
        files={"image": ("label.jpg", image, content_type)},
        data={"application": json.dumps(_application())},
        headers={"X-Real-IP": ip},
    )


@pytest.fixture
def mocked_vision() -> MagicMock:
    service = MagicMock()
    service.extract_preprocessed.return_value = _extracted()
    app.dependency_overrides[get_vision_service_factory] = lambda: lambda: service
    try:
        yield service
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client(mocked_vision: MagicMock) -> TestClient:  # noqa: ARG001
    return TestClient(app)


def test_sixth_request_in_a_minute_is_rejected_before_vision(
    client: TestClient,
    mocked_vision: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = MutableClock(100.0)
    app.state.verify_limiter = VerifyRateLimiter(_settings(), clock=clock)
    caplog.set_level(logging.INFO, logger="uvicorn.error.app.verify")

    assert all(_post(client).status_code == 200 for _ in range(5))
    response = _post(client)

    assert response.status_code == 429
    assert response.json() == {
        "error": {
            "code": "RATE_LIMITED",
            "message": "Too many labels have been checked. Please wait and try again.",
            "field": None,
        }
    }
    assert response.headers["Retry-After"] == "60"
    assert mocked_vision.extract_preprocessed.call_count == 5
    assert "rate_limit_scope=client" in caplog.text
    assert "203.0.113.1" not in caplog.text


@pytest.mark.parametrize("status_code", ["413", "429", "503"])
def test_openapi_documents_structured_service_responses(
    client: TestClient,
    status_code: str,
) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    documented_response = response.json()["paths"]["/verify"]["post"]["responses"][
        status_code
    ]
    schema = documented_response["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/ErrorResponse"}


def test_openapi_documents_request_and_field_size_limits(client: TestClient) -> None:
    document_text = str(client.get("/openapi.json").json())

    assert "21 MiB" in document_text
    assert "20 MiB" in document_text
    assert "2,000 characters per field" in document_text


def test_thirty_first_request_in_an_hour_is_rejected(
    client: TestClient,
    mocked_vision: MagicMock,
) -> None:
    clock = MutableClock()
    app.state.verify_limiter = VerifyRateLimiter(
        _settings(per_minute=100, per_hour=30, global_per_hour=200),
        clock=clock,
    )

    assert all(_post(client).status_code == 200 for _ in range(30))
    response = _post(client)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert response.headers["Retry-After"] == "3600"
    assert mocked_vision.extract_preprocessed.call_count == 30


def test_one_hundred_first_valid_request_hits_global_budget(
    client: TestClient,
    mocked_vision: MagicMock,
) -> None:
    clock = MutableClock()
    app.state.verify_limiter = VerifyRateLimiter(
        _settings(per_minute=200, per_hour=200, global_per_hour=100),
        clock=clock,
    )

    for index in range(100):
        response = _post(client, ip=f"203.0.113.{index + 1}")
        assert response.status_code == 200
    denied = _post(client, ip="198.51.100.1")

    assert denied.status_code == 429
    assert denied.json()["error"]["code"] == "RATE_LIMITED"
    assert denied.headers["Retry-After"] == "3600"
    assert mocked_vision.extract_preprocessed.call_count == 100
    assert app.state.verify_limiter.snapshot().global_attempts == 100


def test_invalid_submission_does_not_consume_global_budget(
    client: TestClient,
    mocked_vision: MagicMock,
) -> None:
    app.state.verify_limiter = VerifyRateLimiter(_settings(per_minute=10))

    invalid = _post(client, image_bytes=b"not an image", content_type="text/plain")

    assert invalid.status_code == 415
    assert app.state.verify_limiter.snapshot().global_attempts == 0
    assert mocked_vision.extract_preprocessed.call_count == 0

    assert _post(client).status_code == 200
    assert app.state.verify_limiter.snapshot().global_attempts == 1


def test_client_ip_limits_are_independent_and_other_routes_are_unrestricted(
    client: TestClient,
    mocked_vision: MagicMock,
) -> None:
    app.state.verify_limiter = VerifyRateLimiter(
        _settings(per_minute=1, per_hour=10),
    )

    assert _post(client, ip="203.0.113.40").status_code == 200
    assert _post(client, ip="203.0.113.40").status_code == 429
    assert _post(client, ip="203.0.113.41").status_code == 200

    for _ in range(10):
        assert client.get("/health").status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200
    assert mocked_vision.extract_preprocessed.call_count == 2


def test_third_simultaneous_verification_is_rejected_as_busy() -> None:
    class BlockingVisionService:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self.entered = 0
            self.two_entered = threading.Event()
            self.release = threading.Event()

        def extract_preprocessed(self, jpeg_bytes: bytes) -> ExtractedLabel:  # noqa: ARG002
            with self._lock:
                self.entered += 1
                if self.entered == 2:
                    self.two_entered.set()
            if not self.release.wait(timeout=5):
                raise TimeoutError("test vision service was not released")
            return _extracted()

    service = BlockingVisionService()
    app.state.verify_limiter = VerifyRateLimiter(
        _settings(per_minute=10, per_hour=10, max_concurrent=2)
    )
    app.dependency_overrides[get_vision_service_factory] = lambda: lambda: service

    def submit(ip: str):  # type: ignore[no-untyped-def]
        with TestClient(app) as thread_client:
            return _post(thread_client, ip=ip)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(submit, "203.0.113.50")
            second = executor.submit(submit, "203.0.113.51")
            assert service.two_entered.wait(timeout=3)

            with TestClient(app) as third_client:
                denied = _post(third_client, ip="203.0.113.52")

            assert denied.status_code == 429
            assert denied.json()["error"]["code"] == "VERIFICATION_BUSY"
            assert denied.headers["Retry-After"] == "5"
            assert service.entered == 2

            service.release.set()
            assert first.result(timeout=3).status_code == 200
            assert second.result(timeout=3).status_code == 200
    finally:
        service.release.set()
        app.dependency_overrides.clear()

    snapshot = app.state.verify_limiter.snapshot()
    assert snapshot.active_verifications == 0
    assert snapshot.global_attempts == 2
