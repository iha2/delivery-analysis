import csv
import io

import pytest

from metrics_seed import SEPT, TODAY, TZ, person, seed
from delivery_analysis.metrics.catalog import BY_NAME
from delivery_analysis.metrics.export import cell, person_csv
from delivery_analysis.metrics.matrix import people_matrix
from delivery_analysis.metrics.people import Scope
from delivery_analysis.metrics.series import KEYS
from delivery_analysis.metrics.window import make_window

WINDOW = make_window(SEPT, TZ, TODAY)
HEADER = ["person", "metric", "label", "group", "value", "unit", "sample", "rank", "ranked", "confidence",
          "status", "window_start", "window_end"]


def run(conn, person_id="p-bob", section="all", scope=None, **kw):
    text = person_csv(conn, person_id, scope or Scope(), WINDOW, section=section, series_end=TODAY,
                      window_days=30, tz=TZ, history_days=90, **kw)
    return text, list(csv.reader(io.StringIO(text, newline="")))


def blocks(rows):
    out, current = [], []
    for row in rows:
        if row == []:
            out.append(current)
            current = []
        else:
            current.append(row)
    out.append(current)
    return out


def test_metrics_header_and_one_row_per_matrix_column(conn):
    seed(conn)
    _, rows = run(conn, section="metrics")
    columns = people_matrix(conn, Scope(), WINDOW, history_days=90)["columns"]
    assert rows[0] == HEADER
    assert [r[1] for r in rows[1:]] == [c["name"] for c in columns]
    first = rows[1]
    assert first[0] == "Bob Builder" and first[3] == BY_NAME[columns[0]["name"]].group
    assert first[11] == WINDOW.start and first[12] == WINDOW.end


def test_waiting_metric_has_blank_values_and_status(conn):
    seed(conn)
    _, rows = run(conn, section="metrics")
    by = {r[1]: r for r in rows[1:]}
    waiting = by["impact_per_dollar"]
    assert waiting[4] == waiting[6] == waiting[7] == waiting[8] == waiting[9] == ""
    assert waiting[10].startswith("waiting for ") and "claude_usage" in waiting[10]
    assert by["prs_reviewed"][10] == "ok" and by["prs_reviewed"][4] != ""


def test_series_block_shape(conn):
    seed(conn)
    _, rows = run(conn, section="series")
    assert rows[0] == ["date", *KEYS, *[f"team_median_{k}" for k in KEYS]]
    assert len(rows) > 2 and all(len(r) == len(rows[0]) for r in rows)
    assert rows[1][0] <= rows[-1][0]


def test_all_has_one_blank_line_between_blocks(conn):
    seed(conn)
    text, rows = run(conn)
    parts = blocks(rows)
    assert len(parts) == 2 and parts[0][0] == HEADER and parts[1][0][0] == "date"
    assert text.count("\r\n\r\n") == 1 and "\n" not in text.replace("\r\n", "")


def test_sections_alone(conn):
    seed(conn)
    _, rows = run(conn, section="metrics")
    assert [] not in rows and rows[0] == HEADER
    _, rows = run(conn, section="series")
    assert [] not in rows and rows[0][0] == "date"


def test_bad_section_raises(conn):
    seed(conn)
    with pytest.raises(ValueError):
        run(conn, section="nope")


def test_person_outside_team_has_blank_cells(conn):
    seed(conn)
    from delivery_analysis.metrics.people import team_scope
    _, rows = run(conn, "p-cy", section="metrics", scope=team_scope(conn, "t1"))
    assert rows[1][0] == "Cy Inactive"
    assert all(r[4] == "" and r[7] == "" for r in rows[1:])


def test_name_with_commas_quotes_and_newlines_round_trips(conn):
    seed(conn)
    name = 'Ann "The, Rock"\nExample'
    person(conn, "p-rock", name, accounts=["acc-rock"])
    _, rows = run(conn, "p-rock", section="metrics")
    assert {r[0] for r in rows[1:]} == {name}


@pytest.mark.parametrize("name", ['=HYPERLINK("http://x.example","a")', "@x", "+1", "-cmd", "\tx", "\rx"])
def test_formula_names_are_guarded(conn, name):
    seed(conn)
    person(conn, "p-evil", name, accounts=["acc-evil"])
    _, rows = run(conn, "p-evil", section="metrics")
    assert rows[1][0] == "'" + name


def test_cell_helper_guards_strings_not_numbers():
    assert cell(-0.15) == -0.15 and cell(3) == 3 and cell(None) == ""
    assert cell("=1+1") == "'=1+1" and cell("plain") == "plain" and cell("") == ""
    assert cell("-x") == "'-x"
    out = io.StringIO()
    csv.writer(out).writerow([cell(-0.15)])
    assert out.getvalue().strip() == "-0.15"
