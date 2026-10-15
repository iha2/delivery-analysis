import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "delivery_analysis" / "app" / "static"
PAGE_FILES = sorted(p for p in STATIC.glob("*.html") if p.name != "index.html")
NAV_LABELS = ["Dashboard", "Rankings", "Selection", "Teams", "Sources", "Settings", "Ask"]
API_ROOTS = {"teams", "metrics", "people", "repos", "sources", "refresh", "settings", "identities", "health"}
OWN_FILES = [p for p in STATIC.rglob("*") if p.suffix in (".html", ".js", ".css") and "vendor" not in p.parts]


def references(html):
    return re.findall(r'(?:src|href)="([^"]+)"', html)


def test_chart_js_is_vendored():
    vendored = (STATIC / "vendor" / "chart.umd.js").read_text(encoding="utf-8", errors="replace")
    assert "Chart.js v4" in vendored[:400]


@pytest.mark.parametrize("page", PAGE_FILES, ids=lambda p: p.name)
def test_every_page_has_the_nav_shared_assets_and_only_local_references(page):
    html = page.read_text(encoding="utf-8")
    for label in NAV_LABELS:
        assert f">{label}</a>" in html
    for needed in ('id="header"', 'id="content"', "/static/style.css", "/static/app.js"):
        assert needed in html
    script = f"/static/pages/{page.stem}.js"
    assert script in html
    for ref in references(html):
        assert ref.startswith("/"), ref
        if ref.startswith("/static/"):
            assert (STATIC / ref[len("/static/"):]).is_file(), ref


@pytest.mark.parametrize("page", PAGE_FILES, ids=lambda p: p.name)
def test_page_scripts_only_use_ids_their_page_has(page):
    html = page.read_text(encoding="utf-8")
    script = (STATIC / "pages" / f"{page.stem}.js").read_text(encoding="utf-8")
    for element_id in re.findall(r'getElementById\("([^"]+)"\)', script):
        assert f'id="{element_id}"' in html, f"{page.stem}.js uses #{element_id}"


@pytest.mark.parametrize("path", OWN_FILES, ids=lambda p: p.name)
def test_no_file_reaches_the_internet_and_api_calls_match_the_contract(path):
    text = path.read_text(encoding="utf-8")
    assert "http://" not in text and "https://" not in text
    for root in re.findall(r'"/api/([a-z_]+)', text):
        assert root in API_ROOTS, f"{path.name} calls /api/{root}"


def test_charts_pages_load_chart_js_before_app_scripts():
    for name in ("dashboard.html", "person.html"):
        html = (STATIC / name).read_text(encoding="utf-8")
        assert html.index("/static/vendor/chart.umd.js") < html.index("/static/charts.js")
