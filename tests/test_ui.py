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
    assert page.count('maxlength="2000"') == 7


def test_page_loads_static_assets() -> None:
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
