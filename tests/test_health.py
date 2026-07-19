from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_serves_verification_page() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Check Alcohol Labels" in response.text
    assert 'id="queue-form"' in response.text
    assert 'id="load-demo-button"' in response.text
    assert "/static/app.js" in response.text
