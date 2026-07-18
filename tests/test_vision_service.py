from io import BytesIO
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ContentFilterFinishReasonError,
    InternalServerError,
    LengthFinishReasonError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from PIL import Image

import app.vision.service as service_module
from app.models import ExtractedLabel
from app.vision import FakeVisionService, VisionService, VisionUnavailableError
from app.vision.prompt import SYSTEM_PROMPT, USER_PROMPT
from app.vision.service import MAX_COMPLETION_TOKENS
from tests.warning_fixtures import ALL_CAPS_WARNING


def _tiny_jpeg() -> bytes:
    image = Image.new("RGB", (32, 32), (240, 230, 210))
    buf = BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


def _parsed_completion(
    parsed: Any,
    *,
    refusal: str | None = None,
) -> SimpleNamespace:
    message = SimpleNamespace(parsed=parsed, refusal=refusal)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def _status_error(error_type: type[Exception], status_code: int) -> Exception:
    return error_type(
        message="test error",
        response=MagicMock(status_code=status_code),
        body=None,
    )


def _full_label() -> ExtractedLabel:
    return ExtractedLabel(
        brand="RIVERBEND RESERVE",
        class_type="Cabernet Sauvignon",
        producer="Riverbend Winery",
        country="USA",
        abv="13.5% alc/vol",
        net_contents="750 mL",
        government_warning=ALL_CAPS_WARNING,
    )


def test_extract_happy_path_uses_structured_format() -> None:
    client = MagicMock()
    client.chat.completions.parse.return_value = _parsed_completion(_full_label())
    service = VisionService(client=client)

    result = service.extract(_tiny_jpeg())

    assert result == _full_label()
    kwargs = client.chat.completions.parse.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["response_format"] is ExtractedLabel
    assert kwargs["max_completion_tokens"] == MAX_COMPLETION_TOKENS
    assert kwargs["messages"][0]["content"] == SYSTEM_PROMPT
    user_content = kwargs["messages"][1]["content"]
    assert user_content[0] == {"type": "text", "text": USER_PROMPT}
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert user_content[1]["image_url"]["detail"] == "high"


def test_extract_preprocessed_skips_preprocessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.chat.completions.parse.return_value = _parsed_completion(_full_label())
    service = VisionService(client=client)
    preprocess = MagicMock(side_effect=AssertionError("must not preprocess twice"))
    monkeypatch.setattr(service_module, "preprocess_image", preprocess)

    result = service.extract_preprocessed(_tiny_jpeg())

    assert result == _full_label()
    preprocess.assert_not_called()


def test_extract_partial_fields() -> None:
    client = MagicMock()
    partial = ExtractedLabel(brand="RIVERBEND RESERVE", government_warning=None)
    client.chat.completions.parse.return_value = _parsed_completion(partial)
    service = VisionService(client=client)

    result = service.extract(_tiny_jpeg())

    assert result.brand == "RIVERBEND RESERVE"
    assert result.government_warning is None
    assert result.abv is None


def test_extract_timeout_raises_unavailable() -> None:
    client = MagicMock()
    client.chat.completions.parse.side_effect = APITimeoutError(request=MagicMock())
    service = VisionService(client=client)

    with pytest.raises(VisionUnavailableError):
        service.extract(_tiny_jpeg())


@pytest.mark.parametrize(
    "error",
    [
        APIConnectionError(request=MagicMock()),
        _status_error(RateLimitError, 429),
        _status_error(InternalServerError, 500),
        ContentFilterFinishReasonError(),
        LengthFinishReasonError(completion=MagicMock(usage=None)),
    ],
)
def test_extract_transient_or_filtered_failure_raises_unavailable(
    error: Exception,
) -> None:
    client = MagicMock()
    client.chat.completions.parse.side_effect = error
    service = VisionService(client=client)

    with pytest.raises(VisionUnavailableError):
        service.extract(_tiny_jpeg())


def test_extract_auth_error_fails_fast() -> None:
    client = MagicMock()
    client.chat.completions.parse.side_effect = AuthenticationError(
        message="invalid key",
        response=MagicMock(status_code=401),
        body=None,
    )
    service = VisionService(client=client)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        service.extract(_tiny_jpeg())


@pytest.mark.parametrize(
    ("error_type", "status_code"),
    [
        (BadRequestError, 400),
        (PermissionDeniedError, 403),
        (NotFoundError, 404),
        (UnprocessableEntityError, 422),
    ],
)
def test_extract_configuration_error_fails_fast(
    error_type: type[Exception],
    status_code: int,
) -> None:
    client = MagicMock()
    client.chat.completions.parse.side_effect = _status_error(
        error_type,
        status_code,
    )
    service = VisionService(client=client)

    with pytest.raises(RuntimeError, match="OPENAI_VISION_MODEL"):
        service.extract(_tiny_jpeg())


def test_extract_parsed_none_raises_unavailable() -> None:
    client = MagicMock()
    client.chat.completions.parse.return_value = _parsed_completion(None)
    service = VisionService(client=client)

    with pytest.raises(VisionUnavailableError):
        service.extract(_tiny_jpeg())


def test_extract_refusal_raises_unavailable() -> None:
    client = MagicMock()
    client.chat.completions.parse.return_value = _parsed_completion(
        None,
        refusal="Unable to process this image.",
    )
    service = VisionService(client=client)

    with pytest.raises(VisionUnavailableError):
        service.extract(_tiny_jpeg())


def test_extract_malformed_parsed_object_raises_unavailable() -> None:
    client = MagicMock()
    client.chat.completions.parse.return_value = _parsed_completion(
        {"brand": {"not": "a string"}}
    )
    service = VisionService(client=client)

    with pytest.raises(VisionUnavailableError):
        service.extract(_tiny_jpeg())


def test_extract_malformed_parsed_object_does_not_log_label_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_label_text = "DO-NOT-LOG-EXTRACTED-LABEL-TEXT"
    client = MagicMock()
    client.chat.completions.parse.return_value = _parsed_completion(
        {"government_warning": {"raw": sensitive_label_text}}
    )
    service = VisionService(client=client)
    caplog.set_level("WARNING", logger="app.vision.service")

    with pytest.raises(VisionUnavailableError):
        service.extract(_tiny_jpeg())

    assert caplog.messages == [
        "vision parsed validation soft-fail: ValidationError"
    ]
    assert sensitive_label_text not in caplog.text


def test_extract_unusable_response_raises_unavailable() -> None:
    client = MagicMock()
    client.chat.completions.parse.return_value = SimpleNamespace(choices=[])
    service = VisionService(client=client)

    with pytest.raises(VisionUnavailableError):
        service.extract(_tiny_jpeg())


def test_extract_valid_all_null_response_remains_a_valid_extraction() -> None:
    client = MagicMock()
    client.chat.completions.parse.return_value = _parsed_completion(ExtractedLabel())
    service = VisionService(client=client)

    assert service.extract(_tiny_jpeg()) == ExtractedLabel()


def test_extract_unexpected_programming_error_is_not_hidden() -> None:
    client = MagicMock()
    client.chat.completions.parse.side_effect = KeyError("programming defect")
    service = VisionService(client=client)

    with pytest.raises(KeyError, match="programming defect"):
        service.extract(_tiny_jpeg())


def test_extract_corrupt_image_returns_empty_without_api_call() -> None:
    client = MagicMock()
    service = VisionService(client=client)

    result = service.extract(b"not-an-image")

    assert result == ExtractedLabel()
    client.chat.completions.parse.assert_not_called()


def test_extract_oversized_image_returns_empty_without_api_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.vision.preprocess.MAX_INPUT_BYTES", 4)
    client = MagicMock()
    service = VisionService(client=client)

    assert service.extract(_tiny_jpeg()) == ExtractedLabel()
    client.chat.completions.parse.assert_not_called()


def test_extract_normalizes_empty_strings_to_none() -> None:
    client = MagicMock()
    client.chat.completions.parse.return_value = _parsed_completion(
        ExtractedLabel(brand="", class_type="  ", producer="Winery")
    )
    service = VisionService(client=client)

    result = service.extract(_tiny_jpeg())

    assert result.brand is None
    assert result.class_type is None
    assert result.producer == "Winery"


def test_extract_preserves_nonempty_warning_verbatim() -> None:
    warning = "  GOVERNMENT WARNING:\nExact punctuation.  "
    client = MagicMock()
    client.chat.completions.parse.return_value = _parsed_completion(
        ExtractedLabel(government_warning=warning)
    )
    service = VisionService(client=client)

    assert service.extract(_tiny_jpeg()).government_warning == warning


def test_missing_api_key_fails_fast_without_injected_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        VisionService()


def test_live_client_disables_retries_and_uses_four_second_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client_factory = MagicMock()
    monkeypatch.setattr(service_module, "OpenAI", client_factory)

    VisionService()

    client_factory.assert_called_once_with(
        api_key="test-key",
        timeout=4.0,
        max_retries=0,
    )


def test_prompt_requires_verbatim_warning_and_partial_degraded_results() -> None:
    assert "character-for-character" in SYSTEM_PROMPT
    assert "visible line breaks" in SYSTEM_PROMPT
    assert "from memory" in SYSTEM_PROMPT
    assert "set government_warning to null" in SYSTEM_PROMPT
    assert "Blurry, rotated, angled" in SYSTEM_PROMPT
    assert "set all seven fields to null" in SYSTEM_PROMPT


def test_fake_vision_service_returns_fixed_result_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    expected = _full_label()
    fake = FakeVisionService(expected)

    result = fake.extract(_tiny_jpeg(), content_type="image/jpeg")

    assert result == expected
    assert len(fake.calls) == 1
    assert fake.calls[0][1] == "image/jpeg"


def test_fake_vision_service_corrupt_image_returns_empty() -> None:
    fake = FakeVisionService(_full_label())
    assert fake.extract(b"garbage") == ExtractedLabel()
