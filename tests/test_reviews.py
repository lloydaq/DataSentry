"""Finding review log: decisions validated as untrusted input, carried in reports, escaped in HTML."""

import json

import pytest

from app.services import report
from app.services.analysis import run_analysis
from app.services.loader import DatasetError
from tests.conftest import load, rows_csv, upload
from tests.test_api import SECRET, assert_safe_error

DATA = rows_csv("x,const,empty", [f"{(i * 37) % 101},same," for i in range(40)])


def findings():
    return run_analysis(load(DATA)).findings


def review(f, status="accepted_risk", note="known and fine", when="2026-01-02T03:04:05Z"):
    return {"finding_code": f.code, "columns": f.columns, "status": status, "note": note, "decided_at": when}


def bad(raw) -> DatasetError:
    with pytest.raises(DatasetError) as info:
        report.parse_reviews(raw if isinstance(raw, str) else json.dumps(raw))
    assert info.value.code == "invalid_reviews"
    return info.value


# --- Parsing untrusted decisions ----------------------------------------------------------------


def test_empty_field_means_no_reviews():
    assert report.parse_reviews("") == [] and report.parse_reviews("   ") == []


def test_valid_reviews_parse():
    f = findings()[0]
    parsed = report.parse_reviews(json.dumps([review(f)]))
    assert parsed[0].finding_code == f.code and parsed[0].status == "accepted_risk"


@pytest.mark.parametrize(
    "item",
    [
        {"finding_code": "x", "columns": [], "status": "approved", "note": "", "decided_at": "t"},  # unknown status
        {"finding_code": "x", "columns": [], "status": "acknowledged", "note": "n" * 281, "decided_at": "t"},
        {"finding_code": "", "columns": [], "status": "acknowledged", "note": "", "decided_at": "t"},
        {"finding_code": "x", "columns": [], "status": "acknowledged", "note": "", "decided_at": ""},
        {"finding_code": "x", "columns": [], "status": "acknowledged", "note": "", "decided_at": "t", "user": "me"},
        {"finding_code": "x", "columns": [1], "status": "acknowledged", "note": "", "decided_at": "t"},
    ],
)
def test_malformed_reviews_are_rejected(item):
    bad([item])


def test_not_json_or_not_a_list_is_rejected():
    bad("not json")
    bad({"reviews": []})


def test_limits_and_duplicates():
    one = {"finding_code": "x", "columns": [], "status": "acknowledged", "note": "", "decided_at": "t"}
    bad([one, one])
    many = [{**one, "finding_code": f"c{i}"} for i in range(report.MAX_REVIEWS + 1)]
    assert "At most" in bad(many).message
    assert len(report.parse_reviews(json.dumps(many[:-1]))) == report.MAX_REVIEWS


def test_error_messages_do_not_echo_input():
    assert SECRET not in bad(SECRET).message


# --- Reports carry only matching decisions ------------------------------------------------------


def test_report_keeps_matching_reviews_in_finding_order():
    result = run_analysis(load(DATA))
    fs = result.findings
    stray = {"finding_code": "not_a_finding", "columns": [], "status": "acknowledged", "note": "", "decided_at": "t"}
    parsed = report.parse_reviews(json.dumps([review(fs[-1], "fixed_upstream"), stray, review(fs[0])]))
    doc = report.build_report(result, False, reviews=parsed)
    assert [r.finding_code for r in doc.reviews] == [fs[0].code, fs[-1].code]


def test_review_for_same_code_but_other_columns_does_not_match():
    result = run_analysis(load(DATA))
    f = result.findings[0]
    other = review(f) | {"columns": ["somewhere_else"]}
    assert report.build_report(result, False, reviews=report.parse_reviews(json.dumps([other]))).reviews == []


def test_report_without_reviews_is_unchanged():
    doc = report.build_report(run_analysis(load(DATA)), False)
    assert doc.reviews == [] and "Review log" not in report.render_html(doc)


def test_html_report_escapes_notes_and_lists_the_log():
    result = run_analysis(load(DATA))
    f = result.findings[0]
    parsed = report.parse_reviews(json.dumps([review(f, note="<script>alert(1)</script> & co")]))
    html = report.render_html(report.build_report(result, False, reviews=parsed))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co" in html
    assert "Review log (1)" in html and "Accepted risk" in html


# --- API ----------------------------------------------------------------------------------------


def test_report_endpoint_round_trips_reviews(client):
    f = findings()[0]
    sent = [review(f, note="checked with the data owner")]
    doc = upload(client, "/api/report", DATA, format="json", reviews=json.dumps(sent)).json()
    assert doc["reviews"] == sent
    # What the browser imports back is exactly what was exported.
    again = upload(client, "/api/report", DATA, format="json", reviews=json.dumps(doc["reviews"])).json()
    assert again["reviews"] == sent


def test_report_endpoint_rejects_invalid_reviews_safely(client):
    assert_safe_error(upload(client, "/api/report", DATA, format="json", reviews=SECRET), 422, "invalid_reviews")


def test_reviews_are_never_stored_on_the_server(client):
    f = findings()[0]
    upload(client, "/api/report", DATA, format="json", reviews=json.dumps([review(f)]))
    assert upload(client, "/api/report", DATA, format="json").json()["reviews"] == []
