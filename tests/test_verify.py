from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.api.verify as verify_module
import app.vision.preprocess as preprocess_module
from app.api.verify import get_vision_service_factory
from app.main import app
from app.models import ExtractedLabel
from tests.warning_fixtures import ALL_CAPS_WARNING, TITLE_CASE_WARNING


def _application(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "brand": "RIVERBEND RESERVE",
        "class_type": "Cabernet Sauvignon",
        "producer": "Riverbend Winery",
        "country": "USA",
        "abv": "13.5%",
        "net_contents": "750 mL",
        "government_warning": ALL_CAPS_WARNING,
    }
    payload.update(updates)
    return payload


def _extracted(**updates: object) -> ExtractedLabel:
    payload: dict[str, object] = {
        "brand": "Riverbend Reserve",
        "class_type": "Cabernet Sauvignon",
        "producer": "Riverbend Winery",
        "country": "United States",
        "abv": "13.5% alc/vol",
        "net_contents": "750ml",
        "government_warning": ALL_CAPS_WARNING,
    }
    payload.update(updates)
    return ExtractedLabel.model_validate(payload)


def _image_bytes(image_format: str = "JPEG", size: tuple[int, int] = (32, 24)) -> bytes:
    image = Image.new("RGB", size, (210, 190, 170))
    buffer = BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def _post(
    client: TestClient,
    *,
    image_bytes: bytes | None = None,
    content_type: str = "image/jpeg",
    application: object | str | None = None,
):  # type: ignore[no-untyped-def]
    files = None
    if image_bytes is not None:
        files = {"image": ("label", image_bytes, content_type)}

    data = None
    if application is not None:
        encoded = (
            application if isinstance(application, str) else json.dumps(application)
        )
        data = {"application": encoded}
    return client.post("/verify", files=files, data=data)


@pytest.fixture
def mocked_vision() -> Iterator[MagicMock]:
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


def test_verify_matching_label_returns_complete_result(
    client: TestClient,
    mocked_vision: MagicMock,
) -> None:
    response = _post(
        client,
        image_bytes=_image_bytes(),
        application=_application(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "PASS"
    assert isinstance(body["latency_ms"], float)
    assert body["latency_ms"] >= 0
    assert len(body["fields"]) == 7
    assert all(result["status"] == "PASS" for result in body["fields"])
    brand = next(result for result in body["fields"] if result["field"] == "brand")
    assert brand["expected"] == "RIVERBEND RESERVE"
    assert brand["actual"] == "Riverbend Reserve"

    jpeg_bytes = mocked_vision.extract_preprocessed.call_args.args[0]
    assert jpeg_bytes.startswith(b"\xff\xd8\xff")


@pytest.mark.parametrize(
    ("image_format", "content_type"),
    [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")],
)
def test_verify_accepts_supported_formats_and_preprocesses_once(
    client: TestClient,
    mocked_vision: MagicMock,
    image_format: str,
    content_type: str,
) -> None:
    response = _post(
        client,
        image_bytes=_image_bytes(image_format),
        content_type=content_type,
        application=_application(),
    )

    assert response.status_code == 200
    jpeg_bytes = mocked_vision.extract_preprocessed.call_args.args[0]
    assert jpeg_bytes.startswith(b"\xff\xd8\xff")
    mocked_vision.extract_preprocessed.assert_called_once()


def test_verify_fuzzy_failure_surfaces_expected_and_found(
    client: TestClient,
    mocked_vision: MagicMock,
) -> None:
    mocked_vision.extract_preprocessed.return_value = _extracted(brand="OTHER BRAND")

    response = _post(client, image_bytes=_image_bytes(), application=_application())

    assert response.status_code == 200
    assert response.json()["verdict"] == "NEEDS_REVIEW"
    brand = next(
        result for result in response.json()["fields"] if result["field"] == "brand"
    )
    assert brand["status"] == "FAIL"
    assert brand["expected"] == "RIVERBEND RESERVE"
    assert brand["actual"] == "OTHER BRAND"


def test_verify_warning_failure_surfaces_extracted_warning_verbatim(
    client: TestClient,
    mocked_vision: MagicMock,
) -> None:
    extracted_warning = f"  {TITLE_CASE_WARNING}\n  "
    mocked_vision.extract_preprocessed.return_value = _extracted(
        government_warning=extracted_warning
    )

    response = _post(client, image_bytes=_image_bytes(), application=_application())

    assert response.status_code == 200
    warning = next(
        result
        for result in response.json()["fields"]
        if result["field"] == "government_warning"
    )
    assert response.json()["verdict"] == "NEEDS_REVIEW"
    assert warning["status"] == "FAIL"
    assert warning["expected"] == ALL_CAPS_WARNING
    assert warning["actual"] == extracted_warning


def test_verify_warning_whitespace_change_fails_exact_match(
    client: TestClient,
    mocked_vision: MagicMock,
) -> None:
    extracted_warning = ALL_CAPS_WARNING.replace(". (2)", ".\n(2)")
    mocked_vision.extract_preprocessed.return_value = _extracted(
        government_warning=extracted_warning
    )

    response = _post(client, image_bytes=_image_bytes(), application=_application())

    assert response.status_code == 200
    warning = next(
        result
        for result in response.json()["fields"]
        if result["field"] == "government_warning"
    )
    assert response.json()["verdict"] == "NEEDS_REVIEW"
    assert warning["status"] == "FAIL"
    assert warning["expected"] == ALL_CAPS_WARNING
    assert warning["actual"] == extracted_warning


def test_verify_soft_empty_extraction_returns_all_missing_failures(
    client: TestClient,
    mocked_vision: MagicMock,
) -> None:
    mocked_vision.extract_preprocessed.return_value = ExtractedLabel()

    response = _post(client, image_bytes=_image_bytes(), application=_application())

    assert response.status_code == 200
    assert response.json()["verdict"] == "NEEDS_REVIEW"
    assert len(response.json()["fields"]) == 7
    assert all(result["status"] == "FAIL" for result in response.json()["fields"])
    assert all(result["expected"] for result in response.json()["fields"])
    assert all(result["actual"] is None for result in response.json()["fields"])


@pytest.mark.parametrize(
    ("image_bytes", "application", "expected_field", "message_fragment"),
    [
        (None, None, None, "Choose an image"),
        (None, _application(), "image", "Choose an image"),
        (_image_bytes(), None, "application", "application data"),
    ],
)
def test_verify_missing_submission_returns_clear_422(
    client: TestClient,
    mocked_vision: MagicMock,
    image_bytes: bytes | None,
    application: object | None,
    expected_field: str | None,
    message_fragment: str,
) -> None:
    response = _post(client, image_bytes=image_bytes, application=application)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MISSING_SUBMISSION"
    assert response.json()["error"]["field"] == expected_field
    assert message_fragment.lower() in response.json()["error"]["message"].lower()
    mocked_vision.extract_preprocessed.assert_not_called()


def test_verify_empty_image_returns_clear_400(
    client: TestClient,
    mocked_vision: MagicMock,
) -> None:
    response = _post(client, image_bytes=b"", application=_application())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMPTY_IMAGE"
    assert "empty" in response.json()["error"]["message"].lower()
    mocked_vision.extract_preprocessed.assert_not_called()


@pytest.mark.parametrize(
    ("application", "status_code", "error_code"),
    [
        ("", 422, "MISSING_SUBMISSION"),
        ("   ", 422, "EMPTY_APPLICATION"),
        ("{bad json", 400, "INVALID_APPLICATION_JSON"),
        ("[]", 422, "INVALID_APPLICATION"),
    ],
)
def test_verify_rejects_empty_or_malformed_application(
    client: TestClient,
    mocked_vision: MagicMock,
    application: str,
    status_code: int,
    error_code: str,
) -> None:
    response = _post(
        client,
        image_bytes=_image_bytes(),
        application=application,
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code
    assert response.json()["error"]["field"] == "application"
    mocked_vision.extract_preprocessed.assert_not_called()


@pytest.mark.parametrize(
    "field_name",
    [
        "brand",
        "class_type",
        "producer",
        "country",
        "abv",
        "net_contents",
        "government_warning",
    ],
)
@pytest.mark.parametrize("invalid_kind", ["missing", "null", "empty", "blank"])
def test_verify_rejects_missing_null_or_blank_required_fields(
    client: TestClient,
    mocked_vision: MagicMock,
    field_name: str,
    invalid_kind: str,
) -> None:
    application = _application()
    if invalid_kind == "missing":
        application.pop(field_name)
    elif invalid_kind == "null":
        application[field_name] = None
    elif invalid_kind == "empty":
        application[field_name] = ""
    else:
        application[field_name] = "   "

    response = _post(client, image_bytes=_image_bytes(), application=application)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_APPLICATION"
    assert response.json()["error"]["field"] == f"application.{field_name}"
    mocked_vision.extract_preprocessed.assert_not_called()


@pytest.mark.parametrize(
    "application",
    [
        _application(brand=123),
        {**_application(), "unexpected": "value"},
    ],
)
def test_verify_rejects_wrong_types_and_unknown_fields(
    client: TestClient,
    mocked_vision: MagicMock,
    application: dict[str, object],
) -> None:
    response = _post(client, image_bytes=_image_bytes(), application=application)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_APPLICATION"
    mocked_vision.extract_preprocessed.assert_not_called()


def test_verify_rejects_unsupported_declared_type(
    client: TestClient,
    mocked_vision: MagicMock,
) -> None:
    response = _post(
        client,
        image_bytes=_image_bytes(),
        content_type="application/octet-stream",
        application=_application(),
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_IMAGE_TYPE"
    assert "JPEG, PNG, or WebP" in response.json()["error"]["message"]
    mocked_vision.extract_preprocessed.assert_not_called()


def test_verify_rejects_unsupported_decoded_format(
    client: TestClient,
    mocked_vision: MagicMock,
) -> None:
    response = _post(
        client,
        image_bytes=_image_bytes("GIF"),
        content_type="image/jpeg",
        application=_application(),
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_IMAGE_TYPE"
    mocked_vision.extract_preprocessed.assert_not_called()


def test_verify_rejects_mime_spoofing(
    client: TestClient,
    mocked_vision: MagicMock,
) -> None:
    response = _post(
        client,
        image_bytes=_image_bytes("PNG"),
        content_type="image/jpeg",
        application=_application(),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IMAGE_TYPE_MISMATCH"
    mocked_vision.extract_preprocessed.assert_not_called()


def test_verify_rejects_corrupt_image(
    client: TestClient,
    mocked_vision: MagicMock,
) -> None:
    response = _post(
        client,
        image_bytes=b"not an image",
        application=_application(),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_IMAGE"
    mocked_vision.extract_preprocessed.assert_not_called()


def test_verify_malformed_multipart_returns_clear_400() -> None:
    client = TestClient(app)

    response = client.post(
        "/verify",
        content=b"invalid multipart body",
        headers={"content-type": "multipart/form-data"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_MULTIPART"
    assert "upload could not be read" in response.json()["error"]["message"].lower()


def test_verify_get_preserves_method_not_allowed_response() -> None:
    client = TestClient(app)

    response = client.get("/verify")

    assert response.status_code == 405
    assert response.json() == {"detail": "Method Not Allowed"}
    assert response.headers["allow"] == "POST"


def test_bad_upload_does_not_construct_live_vision_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_factory = MagicMock()
    monkeypatch.setattr(verify_module, "_cached_vision_service", service_factory)
    client = TestClient(app)

    response = _post(
        client,
        image_bytes=b"not an image",
        content_type="text/plain",
        application=_application(),
    )

    assert response.status_code == 415
    service_factory.assert_not_called()


def test_verify_rejects_oversized_bytes(
    client: TestClient,
    mocked_vision: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify_module, "MAX_INPUT_BYTES", 4)

    response = _post(client, image_bytes=_image_bytes(), application=_application())

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "IMAGE_TOO_LARGE"
    mocked_vision.extract_preprocessed.assert_not_called()


def test_verify_rejects_excessive_dimensions(
    client: TestClient,
    mocked_vision: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preprocess_module, "MAX_INPUT_PIXELS", 10)

    response = _post(
        client,
        image_bytes=_image_bytes(size=(4, 4)),
        application=_application(),
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "IMAGE_TOO_LARGE"
    mocked_vision.extract_preprocessed.assert_not_called()


def test_verify_service_failure_returns_generic_500_without_details(
    client: TestClient,
    mocked_vision: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_detail = "secret internal configuration detail"
    mocked_vision.extract_preprocessed.side_effect = RuntimeError(secret_detail)
    caplog.set_level(logging.ERROR, logger="uvicorn.error.app.verify")

    response = _post(client, image_bytes=_image_bytes(), application=_application())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "VERIFICATION_UNAVAILABLE"
    assert "try again" in response.json()["error"]["message"].lower()
    assert secret_detail not in response.text
    assert "traceback" not in response.text.lower()
    assert secret_detail not in caplog.text
    assert "traceback" not in caplog.text.lower()
    assert "error_type=RuntimeError" in caplog.text


def test_verify_returns_and_logs_deterministic_latency(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    readings = iter([10.0, 10.12345])
    monkeypatch.setattr(verify_module, "_clock", lambda: next(readings))
    caplog.set_level(logging.INFO, logger="uvicorn.error.app.verify")

    response = _post(client, image_bytes=_image_bytes(), application=_application())

    assert response.status_code == 200
    assert response.json()["latency_ms"] == 123.45
    assert "latency_ms=123.45" in caplog.text
    assert "within_budget=True" in caplog.text
    assert "verdict=PASS" in caplog.text


def test_verify_logs_warning_when_five_second_budget_is_exceeded(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    readings = iter([10.0, 15.001])
    monkeypatch.setattr(verify_module, "_clock", lambda: next(readings))
    caplog.set_level(logging.WARNING, logger="uvicorn.error.app.verify")

    response = _post(client, image_bytes=_image_bytes(), application=_application())

    assert response.status_code == 200
    assert response.json()["verdict"] == "PASS"
    assert response.json()["latency_ms"] == 5_001.0
    assert "within_budget=False" in caplog.text
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_verify_logs_client_error_completion(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="uvicorn.error.app.verify")

    response = _post(
        client,
        image_bytes=b"not an image",
        content_type="text/plain",
        application=_application(),
    )

    assert response.status_code == 415
    assert "status_code=415" in caplog.text
    assert "error_code=UNSUPPORTED_IMAGE_TYPE" in caplog.text


def test_verify_logs_unexpected_500_completion(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        verify_module,
        "_parse_application",
        MagicMock(side_effect=KeyError("unexpected parser failure")),
    )
    caplog.set_level(logging.INFO, logger="uvicorn.error.app.verify")
    client = TestClient(app, raise_server_exceptions=False)

    response = _post(client, image_bytes=_image_bytes(), application=_application())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "VERIFICATION_UNAVAILABLE"
    completion_logs = [
        record.message
        for record in caplog.records
        if record.message.startswith("verify_complete")
    ]
    assert len(completion_logs) == 1
    assert "status_code=500" in completion_logs[0]
    assert "error_code=VERIFICATION_UNAVAILABLE" in completion_logs[0]
