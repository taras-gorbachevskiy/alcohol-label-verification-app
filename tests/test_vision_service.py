from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openai import APITimeoutError, AuthenticationError
from PIL import Image

from app.models import ExtractedLabel
from app.vision import FakeVisionService, VisionService
from app.vision.prompt import SYSTEM_PROMPT, USER_PROMPT
from tests.warning_fixtures import ALL_CAPS_WARNING


def _tiny_jpeg() -> bytes:
    image = Image.new("RGB", (32, 32), (240, 230, 210))
    buf = BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


def _parsed_completion(parsed: ExtractedLabel | None) -> SimpleNamespace:
    message = SimpleNamespace(parsed=parsed)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


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
    assert kwargs["response_format"] is ExtractedLabel
    assert kwargs["messages"][0]["content"] == SYSTEM_PROMPT
    user_content = kwargs["messages"][1]["content"]
    assert user_content[0] == {"type": "text", "text": USER_PROMPT}
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_extract_partial_fields() -> None:
    client = MagicMock()
    partial = ExtractedLabel(brand="RIVERBEND RESERVE", government_warning=None)
    client.chat.completions.parse.return_value = _parsed_completion(partial)
    service = VisionService(client=client)

    result = service.extract(_tiny_jpeg())

    assert result.brand == "RIVERBEND RESERVE"
    assert result.government_warning is None
    assert result.abv is None


def test_extract_timeout_returns_empty() -> None:
    client = MagicMock()
    client.chat.completions.parse.side_effect = APITimeoutError(request=MagicMock())
    service = VisionService(client=client)

    result = service.extract(_tiny_jpeg())

    assert result == ExtractedLabel()


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


def test_extract_parsed_none_returns_empty() -> None:
    client = MagicMock()
    client.chat.completions.parse.return_value = _parsed_completion(None)
    service = VisionService(client=client)

    assert service.extract(_tiny_jpeg()) == ExtractedLabel()


def test_extract_unusable_response_returns_empty() -> None:
    client = MagicMock()
    client.chat.completions.parse.return_value = SimpleNamespace(choices=[])
    service = VisionService(client=client)

    assert service.extract(_tiny_jpeg()) == ExtractedLabel()


def test_extract_corrupt_image_returns_empty_without_api_call() -> None:
    client = MagicMock()
    service = VisionService(client=client)

    result = service.extract(b"not-an-image")

    assert result == ExtractedLabel()
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


def test_missing_api_key_fails_fast_without_injected_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        VisionService()


def test_fake_vision_service_returns_fixed_result() -> None:
    expected = _full_label()
    fake = FakeVisionService(expected)

    result = fake.extract(_tiny_jpeg(), content_type="image/jpeg")

    assert result == expected
    assert len(fake.calls) == 1
    assert fake.calls[0][1] == "image/jpeg"


def test_fake_vision_service_corrupt_image_returns_empty() -> None:
    fake = FakeVisionService(_full_label())
    assert fake.extract(b"garbage") == ExtractedLabel()
