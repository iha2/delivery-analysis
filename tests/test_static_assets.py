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


def read(*parts):
    return STATIC.joinpath(*parts).read_text(encoding="utf-8")


def test_series_two_and_three_exist_in_both_colour_modes_with_the_reference_palette():
    light, _, dark = read("style.css").partition("@media (prefers-color-scheme: dark)")
    for name, value in (("--series-2", "#eb6834"), ("--series-3", "#1baf7a")):
        assert f"{name}: {value};" in light
    for name, value in (("--series-2", "#d95926"), ("--series-3", "#199e70")):
        assert f"{name}: {value};" in dark
    assert ".chart.small" in read("style.css")


def test_charts_js_exposes_series_and_scatter_with_legend_and_axis_titles():
    text = read("charts.js")
    assert "series: function" in text and "scatter: function" in text
    assert "datasets.length > 1" in text  # a legend only when there are two or more series
    assert 'token("--series-" + ' in text
    assert "title: { display: true" in text  # scatter axes are labelled
    assert "yAxisID" not in text and 'position: "right"' not in text  # no dual axis


def test_dashboard_cards_come_in_the_planned_order():
    script = read("pages", "dashboard.js")
    render = script[script.index("DA.page("):]
    calls = ["impact(cards)", "whereItWent(cards)", "howFast(cards)", "evidence(cards)", "impactPerToken(cards)",
             "costVsPoints(cards)", "askVsGenerate(cards)", "throughput(cards)", "timeToMerge(cards)",
             "breakdown(cards)"]
    positions = [render.index(call) for call in calls]
    assert positions == sorted(positions)
    assert render.index('"review_load"') > positions[-1]


def test_dashboard_reads_every_impact_metric_by_name():
    script = read("pages", "dashboard.js")
    for name in ("story_points_weekly", "story_points_done", "points_by_type", "cycle_time_weekly", "cycle_time_summary",
                 "prs_linked_weekly", "prs_with_issue_link", "story_points_per_dollar",
                 "ask_generate_ratio", "issues_done_weekly", "prs_merged_weekly"):
        assert f'"{name}"' in script, name


def test_the_impact_tile_reads_the_servers_trend_and_computes_nothing_in_the_browser():
    script = read("pages", "dashboard.js")
    assert 'sum(weekly.rows, "issues")' in script and 'sum(weekly.rows, "unpointed")' in script
    assert "done.team.trend" in script and "done.team.previous" in script
    block = script[script.index("function impact"):]
    block = block[: block.index("function whereItWent")]
    assert "before" not in block and ".previous ||" not in block and "mapped" not in block
    assert "Median to first PR merge" in script and "pr_median" in script and "credited to the authors" in script


def test_the_waiting_list_skips_metrics_that_already_have_a_card():
    script = read("pages", "dashboard.js")
    assert "ON_CARDS" in script and "ON_CARDS.indexOf(m.name)" in script


def test_cost_based_cards_use_the_friendly_waiting_message():
    app = read("app.js")
    assert "Claude usage" in app and "DA.sourceLabel" in app
    assert "points_per_usd" in app


def test_the_ask_card_is_context_not_a_ranking():
    script = read("pages", "dashboard.js")
    assert "Context only" in script
    block = script[script.index("function askVsGenerate"):]
    block = block[: block.index("function throughput")]
    assert "rank" not in block


def test_person_page_has_points_cycle_time_and_completed_issues():
    script = read("pages", "person.js")
    html = read("person.html")
    for name in ("story_points_done", "cycle_time", "issues_done"):
        assert f'"{name}"' in script, name
    assert "d.issues_done" in script and "i.basis" in script and "i.share" in script
    assert 'id="person-issues"' in html and 'id="person-issues-card"' in html
    assert "hidden" in html.split('id="person-issues-card"')[0].split("<section")[-1]
