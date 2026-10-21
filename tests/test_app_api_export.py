import csv
import io

import pytest

from test_app_api import make
from metrics_seed import person
from delivery_analysis.store import db

URL = "/api/people/p-ann/export.csv"


def parse(response):
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"), newline="")))


def test_download_headers_bom_and_body(tmp_path):
    client, *_ = make(tmp_path)
    r = client.get(URL, params={"team": "t1", "window": "month:2026-09"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == 'attachment; filename="ann-example-metrics-september-2026.csv"'
    assert r.content.startswith(b"\xef\xbb\xbf") and b"\r\n" in r.content
    rows = parse(r)
    assert rows[0][:3] == ["person", "metric", "label"] and [] in rows
    assert any(row and row[0] == "date" for row in rows)


def test_sections(tmp_path):
    client, *_ = make(tmp_path)
    metrics = parse(client.get(URL, params={"section": "metrics", "window": "month:2026-09"}))
    series = parse(client.get(URL, params={"section": "series", "window_days": 14}))
    assert metrics[0][0] == "person" and [] not in metrics
    assert series[0][0] == "date" and [] not in series


def test_awkward_name_round_trips_and_slug_is_ascii(tmp_path):
    client, path, *_ = make(tmp_path)
    conn = db.connect(path)
    person(conn, "p-rock", 'Ann "The, Rock" Example', accounts=["acc-rock"])
    conn.commit()
    conn.close()
    r = client.get("/api/people/p-rock/export.csv", params={"section": "metrics", "window": "month:2026-09"})
    assert parse(r)[1][0] == 'Ann "The, Rock" Example'
    assert 'filename="ann-the-rock-example-metrics-september-2026.csv"' in r.headers["content-disposition"]


def test_slug_falls_back_to_person(tmp_path):
    client, path, *_ = make(tmp_path)
    conn = db.connect(path)
    person(conn, "p-sym", "???", accounts=["acc-sym"])
    conn.commit()
    conn.close()
    r = client.get("/api/people/p-sym/export.csv", params={"window": "month:2026-09"})
    assert r.headers["content-disposition"].startswith('attachment; filename="person-metrics-')


@pytest.mark.parametrize(
    "path, params, status",
    [("/api/people/nobody/export.csv", {}, 404), (URL, {"team": "nope"}, 404),
     (URL, {"window": "weekly"}, 400), (URL, {"section": "nope"}, 400), (URL, {"window_days": 3}, 400),
     (URL, {"window_days": 400}, 400)],
)
def test_errors(tmp_path, path, params, status):
    client, *_ = make(tmp_path)
    r = client.get(path, params=params)
    assert r.status_code == status and r.json()["detail"]
