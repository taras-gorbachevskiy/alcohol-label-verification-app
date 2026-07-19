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


def test_queue_page_has_required_controls() -> None:
    response = client.get("/")

    assert response.status_code == 200
    page = response.text
    assert 'id="queue-form"' in page
    assert 'type="file"' in page
    assert 'accept="image/jpeg,image/png,image/webp"' in page
    assert 'id="add-to-queue-button"' in page
    assert 'id="cancel-compose-button"' in page
    assert "Add to Queue" in page
    assert 'id="load-demo-button"' in page
    assert "Load 3 demo labels" in page
    assert 'class="intro-text-link"' in page
    assert 'href="#queue-form"' in page
    assert "Add one or more labels (up to five)" in page
    assert 'id="check-button"' in page
    assert "Check Labels" in page
    assert 'id="queue-list"' in page
    assert 'id="compose-card"' in page
    assert 'id="results"' in page
    assert 'id="error-summary"' in page
    assert 'id="result-timing"' in page
    for field_name in FIELD_NAMES:
        assert f'name="{field_name}"' in page
    assert page.count('maxlength="2000"') == 7


def test_demo_static_assets_are_served() -> None:
    manifest = client.get("/static/demo/scenarios.json")
    assert manifest.status_code == 200
    scenarios = manifest.json()
    assert isinstance(scenarios, list)
    assert len(scenarios) == 3
    assert scenarios[0]["application"]["brand"] == "RIVERBEND RESERVE"
    assert scenarios[1]["application"]["brand"] == "NOT THE LABEL BRAND"

    clean = client.get("/static/demo/01-clean-exact-match.jpg")
    blur = client.get("/static/demo/03-imperfect-blur.jpg")
    assert clean.status_code == 200
    assert blur.status_code == 200
    assert "image" in clean.headers["content-type"]
    assert "image" in blur.headers["content-type"]


def test_page_has_no_single_batch_mode_toggle() -> None:
    response = client.get("/")

    assert response.status_code == 200
    page = response.text
    assert 'id="single-mode-button"' not in page
    assert 'id="batch-mode-button"' not in page
    assert 'id="verification-form"' not in page
    assert 'id="batch-form"' not in page
    assert 'id="add-label-button"' not in page
    assert 'id="check-progress"' in page
    assert 'aria-label="Label verification in progress"' in page
    assert 'id="summary"' in page
    assert 'id="result-list"' in page
    assert 'class="skip-link"' in page
    assert page.count('aria-live="polite"') >= 2
    assert page.count('aria-atomic="true"') == 1


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


def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    light, dark = sorted(
        (_relative_luminance(first), _relative_luminance(second)), reverse=True
    )
    return (light + 0.05) / (dark + 0.05)


def test_phase6_colors_meet_wcag_normal_text_contrast() -> None:
    pairs = [
        ("#17202a", "#ffffff"),
        ("#4c5967", "#ffffff"),
        ("#ffffff", "#005ea8"),
        ("#a6192e", "#fff2f3"),
        ("#176b3a", "#edf8f1"),
        ("#9f2d20", "#fff1ee"),
    ]
    assert all(_contrast(foreground, background) >= 4.5 for foreground, background in pairs)


def test_phase6_styles_keep_senior_friendly_size_focus_and_reflow() -> None:
    stylesheet = client.get("/static/styles.css").text

    assert "font-size: 1.125rem" in stylesheet
    assert "min-height: 3.75rem" in stylesheet
    assert "min-height: 3rem" in stylesheet
    assert "summary:focus-visible" in stylesheet
    assert "box-shadow: 0 0 0 6px var(--blue)" in stylesheet
    assert "@media (prefers-reduced-motion: reduce)" in stylesheet
    assert "animation: none" in stylesheet
    assert "width: min(100% - 1rem, 46rem)" in stylesheet
    assert ".queue-item" in stylesheet
    assert ".mode-picker" not in stylesheet
    assert ".batch-card-heading" not in stylesheet
    assert ".add-label-button" not in stylesheet
    assert ".verdict.approved" not in stylesheet
    assert ".loading-status" not in stylesheet
