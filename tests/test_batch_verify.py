from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.api.batch_verify as batch_module
from app.api.batch_verify import get_async_vision_service_factory
from app.body_limit import MAX_BATCH_REQUEST_BYTES
from app.main import app
from app.models import ExtractedLabel
from app.rate_limit import RateLimitSettings, VerifyRateLimiter
from app.vision import VisionUnavailableError
from tests.warning_fixtures import ALL_CAPS_WARNING


def _application(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "brand": "CEDAR RIDGE",
        "class_type": "Dry Red Wine",
        "producer": "Cedar Ridge Cellars",
        "country": "USA",
        "abv": "12.5%",
        "net_contents": "750 mL",
        "government_warning": ALL_CAPS_WARNING,
    }
    payload.update(updates)
    return payload


def _extracted(**updates: object) -> ExtractedLabel:
    payload: dict[str, object] = {
        "brand": "Cedar Ridge",
        "class_type": "Dry Red Wine",
        "producer": "Cedar Ridge Cellars",
        "country": "United States",
        "abv": "12.5% alc/vol",
        "net_contents": "750ml",
        "government_warning": ALL_CAPS_WARNING,
    }
    payload.update(updates)
    return ExtractedLabel.model_validate(payload)


def _image_bytes(color: tuple[int, int, int] = (180, 160, 140)) -> bytes:
    image = Image.new("RGB", (36, 24), color)
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _post_batch(
    client: TestClient,
    applications: list[object],
    *,
    images: list[bytes] | None = None,
    ip: str = "203.0.113.120",
):  # type: ignore[no-untyped-def]
    image_values = images or [_image_bytes() for _ in applications]
    files = [
        ("images", (f"label-{index + 1}.jpg", value, "image/jpeg"))
        for index, value in enumerate(image_values)
    ]
    return client.post(
        "/verify/batch",
        files=files,
        data={"applications": json.dumps(applications)},
        headers={"X-Real-IP": ip},
    )


class SequenceAsyncVision:
    def __init__(self, outcomes: list[ExtractedLabel | Exception]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def extract_preprocessed(self, jpeg_bytes: bytes) -> ExtractedLabel:  # noqa: ARG002
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def reset_limiter() -> Iterator[None]:
    app.state.verify_limiter = VerifyRateLimiter(
        RateLimitSettings(
            per_minute=50,
            per_hour=100,
            global_per_hour=100,
            max_concurrent=5,
        )
    )
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def test_batch_isolates_invalid_images_applications_and_provider_errors() -> None:
    service = SequenceAsyncVision(
        [
            _extracted(),
            VisionUnavailableError("provider detail must not escape"),
            _extracted(brand="Different Brand"),
        ]
    )
    app.dependency_overrides[get_async_vision_service_factory] = lambda: lambda: service

    with TestClient(app) as client:
        response = _post_batch(
            client,
            [
                _application(),
                _application(brand=""),
                _application(),
                _application(),
                _application(),
            ],
            images=[
                _image_bytes((180, 160, 140)),
                _image_bytes((181, 161, 141)),
                b"not-an-image",
                _image_bytes((183, 163, 143)),
                _image_bytes((184, 164, 144)),
            ],
        )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {
        "passed": 1,
        "needs_review": 1,
        "unable_to_verify": 3,
        "total": 5,
    }
    assert [item["index"] for item in body["items"]] == list(range(5))
    assert [item["status"] for item in body["items"]] == [
        "PASS",
        "UNABLE_TO_VERIFY",
        "UNABLE_TO_VERIFY",
        "UNABLE_TO_VERIFY",
        "NEEDS_REVIEW",
    ]
    assert body["items"][1]["error"]["code"] == "INVALID_APPLICATION"
    assert body["items"][2]["error"]["code"] == "INVALID_IMAGE"
    assert body["items"][3]["error"]["code"] == "VERIFICATION_UNAVAILABLE"
    assert "provider detail" not in response.text
    assert service.calls == 3
    snapshot = app.state.verify_limiter.snapshot()
    assert snapshot.global_attempts == 3
    assert snapshot.active_verifications == 0


def test_all_locally_invalid_items_return_batch_shaped_422_without_paid_calls() -> None:
    service = SequenceAsyncVision([])
    app.dependency_overrides[get_async_vision_service_factory] = lambda: lambda: service

    with TestClient(app) as client:
        response = _post_batch(
            client,
            [_application(brand=""), _application()],
            images=[_image_bytes(), b"corrupt"],
        )

    assert response.status_code == 422
    assert response.json()["summary"] == {
        "passed": 0,
        "needs_review": 0,
        "unable_to_verify": 2,
        "total": 2,
    }
    assert all(
        item["status"] == "UNABLE_TO_VERIFY" for item in response.json()["items"]
    )
    assert service.calls == 0
    assert app.state.verify_limiter.snapshot().global_attempts == 0


def test_all_provider_failures_return_batch_shaped_503() -> None:
    service = SequenceAsyncVision(
        [VisionUnavailableError("first"), VisionUnavailableError("second")]
    )
    app.dependency_overrides[get_async_vision_service_factory] = lambda: lambda: service

    with TestClient(app) as client:
        response = _post_batch(client, [_application(), _application()])

    assert response.status_code == 503
    assert response.json()["summary"]["unable_to_verify"] == 2
    assert "first" not in response.text
    assert "second" not in response.text
    assert app.state.verify_limiter.snapshot().active_verifications == 0


def test_structural_pair_mismatch_rejects_the_request() -> None:
    service = SequenceAsyncVision([])
    app.dependency_overrides[get_async_vision_service_factory] = lambda: lambda: service

    with TestClient(app) as client:
        response = _post_batch(
            client,
            [_application(), _application()],
            images=[_image_bytes()],
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "BATCH_PAIR_COUNT_MISMATCH"
    assert service.calls == 0


def test_structural_batch_failure_consumes_a_client_attempt() -> None:
    app.state.verify_limiter = VerifyRateLimiter(
        RateLimitSettings(
            per_minute=1,
            per_hour=10,
            global_per_hour=100,
            max_concurrent=5,
        )
    )
    service = SequenceAsyncVision([])
    app.dependency_overrides[get_async_vision_service_factory] = lambda: lambda: service

    with TestClient(app) as client:
        invalid = _post_batch(
            client,
            [_application(), _application()],
            images=[_image_bytes()],
            ip="203.0.113.121",
        )
        limited = _post_batch(
            client,
            [_application()],
            ip="203.0.113.121",
        )

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "BATCH_PAIR_COUNT_MISMATCH"
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert service.calls == 0


def test_five_batch_items_start_concurrently_and_release_all_slots() -> None:
    class BlockingAsyncVision:
        def __init__(self) -> None:
            self.entered = 0
            self.lock = threading.Lock()
            self.all_entered = threading.Event()
            self.release = threading.Event()

        async def extract_preprocessed(self, jpeg_bytes: bytes) -> ExtractedLabel:  # noqa: ARG002
            with self.lock:
                self.entered += 1
                if self.entered == 5:
                    self.all_entered.set()
            released = await asyncio.to_thread(self.release.wait, 3)
            if not released:
                raise TimeoutError("test release timed out")
            return _extracted()

    service = BlockingAsyncVision()
    app.dependency_overrides[get_async_vision_service_factory] = lambda: lambda: service

    def submit():  # type: ignore[no-untyped-def]
        with TestClient(app) as client:
            return _post_batch(client, [_application() for _ in range(5)])

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(submit)
        assert service.all_entered.wait(timeout=3)
        assert service.entered == 5
        assert app.state.verify_limiter.snapshot().active_verifications == 5
        service.release.set()
        response = future.result(timeout=3)

    assert response.status_code == 200
    assert response.json()["summary"]["passed"] == 5
    assert app.state.verify_limiter.snapshot().active_verifications == 0


def test_batch_charges_client_quota_per_submitted_label() -> None:
    app.state.verify_limiter = VerifyRateLimiter(
        RateLimitSettings(
            per_minute=5,
            per_hour=20,
            global_per_hour=100,
            max_concurrent=5,
        )
    )
    service = SequenceAsyncVision([_extracted() for _ in range(5)])
    app.dependency_overrides[get_async_vision_service_factory] = lambda: lambda: service

    with TestClient(app) as client:
        accepted = _post_batch(client, [_application() for _ in range(5)])
        limited = _post_batch(client, [_application()], images=[_image_bytes()])

    assert accepted.status_code == 200
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert service.calls == 5


def test_busy_batch_starts_no_provider_calls() -> None:
    app.state.verify_limiter = VerifyRateLimiter(
        RateLimitSettings(
            per_minute=20,
            per_hour=20,
            global_per_hour=100,
            max_concurrent=2,
        )
    )
    decision, held = app.state.verify_limiter.acquire_processing_slots(1)
    assert decision.allowed
    service = SequenceAsyncVision([_extracted(), _extracted()])
    app.dependency_overrides[get_async_vision_service_factory] = lambda: lambda: service
    try:
        with TestClient(app) as client:
            response = _post_batch(client, [_application(), _application()])
    finally:
        held[0].release()

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "VERIFICATION_BUSY"
    assert service.calls == 0
    assert app.state.verify_limiter.snapshot().active_verifications == 0


def test_batch_deadline_cancels_unfinished_items_and_releases_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowAsyncVision:
        def __init__(self) -> None:
            self.cancelled = 0

        async def extract_preprocessed(self, jpeg_bytes: bytes) -> ExtractedLabel:  # noqa: ARG002
            try:
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
            return _extracted()

    monkeypatch.setattr(batch_module, "BATCH_PROCESSING_DEADLINE_SECONDS", 0.2)
    service = SlowAsyncVision()
    app.dependency_overrides[get_async_vision_service_factory] = lambda: lambda: service

    with TestClient(app) as client:
        response = _post_batch(client, [_application(), _application()])

    assert response.status_code == 503
    assert response.json()["summary"]["unable_to_verify"] == 2
    assert service.cancelled == 2
    assert app.state.verify_limiter.snapshot().active_verifications == 0


def test_preprocessing_past_deadline_retains_slots_until_workers_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.state.verify_limiter = VerifyRateLimiter(
        RateLimitSettings(
            per_minute=20,
            per_hour=20,
            global_per_hour=100,
            max_concurrent=2,
        )
    )
    original_prepare = batch_module._prepare_item
    release_workers = threading.Event()
    all_workers_entered = threading.Event()
    entered = 0
    entered_lock = threading.Lock()

    def stalled_prepare(image, application):  # type: ignore[no-untyped-def]
        nonlocal entered
        with entered_lock:
            entered += 1
            if entered == 2:
                all_workers_entered.set()
        release_workers.wait(timeout=3)
        return original_prepare(image, application)

    monkeypatch.setattr(batch_module, "_prepare_item", stalled_prepare)
    monkeypatch.setattr(batch_module, "BATCH_PROCESSING_DEADLINE_SECONDS", 0.1)
    service = SequenceAsyncVision([])
    app.dependency_overrides[get_async_vision_service_factory] = lambda: lambda: service

    try:
        with TestClient(app) as client:
            timed_out = _post_batch(
                client,
                [_application(), _application()],
                ip="203.0.113.122",
            )

            assert timed_out.status_code == 503
            assert all_workers_entered.wait(timeout=1)
            assert app.state.verify_limiter.snapshot().active_verifications == 2

            busy = _post_batch(
                client,
                [_application()],
                ip="203.0.113.123",
            )
            assert busy.status_code == 429
            assert busy.json()["error"]["code"] == "VERIFICATION_BUSY"

            release_workers.set()
            wait_deadline = time.monotonic() + 2
            while (
                app.state.verify_limiter.snapshot().active_verifications
                and time.monotonic() < wait_deadline
            ):
                time.sleep(0.01)
            assert app.state.verify_limiter.snapshot().active_verifications == 0
    finally:
        release_workers.set()


def test_batch_declared_body_limit_is_enforced_before_parsing() -> None:
    app.state.verify_limiter = VerifyRateLimiter(
        RateLimitSettings(
            per_minute=1,
            per_hour=10,
            global_per_hour=100,
            max_concurrent=5,
        )
    )
    service = SequenceAsyncVision([])
    app.dependency_overrides[get_async_vision_service_factory] = lambda: lambda: service

    with TestClient(app) as client:
        response = client.post(
            "/verify/batch",
            content=b"not parsed",
            headers={
                "Content-Type": "multipart/form-data; boundary=unused",
                "Content-Length": str(MAX_BATCH_REQUEST_BYTES + 1),
                "X-Real-IP": "203.0.113.124",
            },
        )
        limited = client.post(
            "/verify/batch",
            content=b"not parsed",
            headers={
                "Content-Type": "multipart/form-data; boundary=unused",
                "X-Real-IP": "203.0.113.124",
            },
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert service.calls == 0


def test_openapi_documents_batch_contract() -> None:
    with TestClient(app) as client:
        document = client.get("/openapi.json").json()

    operation = document["paths"]["/verify/batch"]["post"]
    assert set(operation["responses"]) >= {"200", "413", "422", "429", "503"}
    assert "one to five" in str(document).lower()
