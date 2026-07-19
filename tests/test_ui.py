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


def test_page_has_accessible_batch_mode_and_results_controls() -> None:
    response = client.get("/")

    assert response.status_code == 200
    page = response.text
    assert 'id="single-mode-button"' in page
    assert 'id="batch-mode-button"' in page
    assert 'id="batch-form"' in page
    assert 'id="add-label-button"' in page
    assert 'id="batch-progress"' in page
    assert 'aria-label="Batch verification in progress"' in page
    assert 'id="batch-summary"' in page
    assert 'id="batch-result-list"' in page
    assert 'class="skip-link"' in page
    assert page.count('aria-live="polite"') >= 3
    assert page.count('aria-atomic="true"') == 2


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
