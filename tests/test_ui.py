from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

FIELD_NAMES = (
    "brand",
    "class_type",
    "producer",
    "country",
    "abv",
    "net_contents",
    "government_warning",
)


def test_single_label_page_has_required_controls() -> None:
    response = client.get("/")

    assert response.status_code == 200
    page = response.text
    assert 'type="file"' in page
    assert 'accept="image/jpeg,image/png,image/webp"' in page
    assert 'id="submit-button"' in page
    assert "Check Label" in page
    assert 'id="results"' in page
    assert 'id="error-summary"' in page
    for field_name in FIELD_NAMES:
        assert f'name="{field_name}"' in page


def test_page_loads_versioned_static_assets() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/static/styles.css"' in response.text
    assert 'src="/static/app.js"' in response.text

    stylesheet = client.get("/static/styles.css")
    script = client.get("/static/app.js")
    assert stylesheet.status_code == 200
    assert "text/css" in stylesheet.headers["content-type"]
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]


def test_browser_controller_posts_expected_multipart_contract() -> None:
    script = client.get("/static/app.js").text

    assert 'fetch("/verify"' in script
    assert 'formData.append("image"' in script
    assert 'formData.append("application"' in script
    assert "JSON.stringify(applicationPayload())" in script
    for field_name in FIELD_NAMES:
        assert f'key: "{field_name}"' in script


def test_results_and_errors_use_plain_language() -> None:
    script = client.get("/static/app.js").text

    assert "APPROVED" in script
    assert "NEEDS REVIEW" in script
    assert "Should say" in script
    assert "Label says" in script
    assert "Not found on the photo" in script
    assert "Check your internet connection and try again" in script
    assert "Your information is still here" in script
    assert 'code === "RATE_LIMITED"' in script
    assert 'code === "VERIFICATION_BUSY"' in script
    assert 'response.headers.get("Retry-After")' in script
    assert "Too many labels have been checked" in script
    assert "The checker is busy" in script

    request_error_handler = script.split("function showRequestError", 1)[1].split(
        "function isValidResult", 1
    )[0]
    assert "form.reset" not in request_error_handler
