"""HTTP integration, error handling and security boundaries."""

import json
import logging
import tempfile

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.config import Limits
from app.main import create_app
from tests.conftest import TEST_LIMITS, upload

SECRET = "SECRET-CELL-7731"
GOOD = "id,score,group,label\n" + "".join(
    f"{i},{i * 1.5},{'ab'[i % 2]},{'yn'[i % 3 == 0]}\n" for i in range(40)
)


def assert_safe_error(response, status: int, code: str):
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error", "message"}
    assert body["error"] == code
    assert "Traceback" not in response.text and SECRET not in response.text


def test_health_reports_version_and_limits(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["limits"]["max_upload_bytes"] == TEST_LIMITS.max_upload_bytes


def test_analyze_success_with_target(client):
    response = upload(client, "/api/analyze", GOOD, target_column="label")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["dataset"]["n_rows"] == 40 and body["settings"]["target_column"] == "label"
    assert body["target"]["task"] == "classification"
    assert {"overview", "columns", "duplicates", "findings", "summary", "corrections"} <= set(body)


def test_analyze_is_deterministic_over_http(client):
    a = upload(client, "/api/analyze", GOOD, target_column="label").json()
    b = upload(client, "/api/analyze", GOOD, target_column="label").json()
    assert a == b


def test_blank_target_means_no_target(client):
    body = upload(client, "/api/analyze", GOOD, target_column="  ").json()
    assert body["settings"]["target_column"] is None and body["target"] is None


def test_degenerate_single_cell_dataset(client):
    body = upload(client, "/api/analyze", "only\n1\n").json()
    assert body["dataset"]["n_rows"] == 1
    assert body["columns"][0]["numeric"]["std"] is None


def test_unicode_and_markup_names_round_trip_as_data(client):
    text = 'naïve,"<img src=x onerror=alert(1)>",名前\n1,"<b>bold</b>",x\n2,y,z\n'
    response = upload(client, "/api/analyze", text)
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert [c["name"] for c in body["columns"]] == ["naïve", "<img src=x onerror=alert(1)>", "名前"]


@pytest.mark.parametrize(
    "content, status, code",
    [
        (b"", 422, "empty_file"),
        (b"a,a\n1,2\n", 422, "duplicate_header"),
        (f"a,b\n{SECRET},1,2\n".encode(), 422, "malformed_csv"),
        (b"a,b\n\xff\xfe,1\n", 422, "invalid_encoding"),
        (b"PK\x03\x04binary", 415, "unsupported_format"),
        (b"a\n" + b"1\n" * 2001, 413, "too_many_rows"),
        (",".join(f"c{i}" for i in range(41)).encode() + b"\n", 413, "too_many_columns"),
    ],
)
def test_invalid_uploads_fail_safely(client, content, status, code):
    assert_safe_error(upload(client, "/api/analyze", content), status, code)


def test_unknown_target_column(client):
    assert_safe_error(upload(client, "/api/analyze", GOOD, target_column="nope"), 422, "unknown_target_column")


def test_missing_file_field(client):
    response = client.post("/api/analyze", files={"other": ("x.csv", b"a\n1\n")})
    assert_safe_error(response, 422, "missing_file")


def test_non_multipart_request_is_rejected(client):
    response = client.post("/api/analyze", content=b"a,b\n1,2\n", headers={"content-type": "text/csv"})
    assert_safe_error(response, 415, "unsupported_media_type")


def test_malformed_multipart_is_rejected(client):
    response = client.post(
        "/api/analyze",
        content=b"--zzz\r\ngarbage",
        headers={"content-type": "multipart/form-data; boundary=zzz"},
    )
    assert response.status_code in (400, 422)
    assert set(response.json()) == {"error", "message"}


def test_wrong_extension_is_rejected(client):
    assert_safe_error(upload(client, "/api/analyze", GOOD, filename="data.xlsx"), 415, "unsupported_format")


def test_oversized_upload_is_rejected_by_declared_length(client):
    big = b"a\n" + b"1\n" * 200_000
    assert_safe_error(upload(client, "/api/analyze", big), 413, "file_too_large")


def test_oversized_upload_is_rejected_while_streaming(client):
    def chunks():
        yield b"--b\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.csv\"\r\n\r\n"
        for _ in range(100):
            yield b"1\n" * 5_000
        yield b"\r\n--b--\r\n"

    response = client.post(
        "/api/analyze", content=chunks(), headers={"content-type": "multipart/form-data; boundary=b"}
    )
    assert_safe_error(response, 413, "file_too_large")


def test_upload_size_check_is_per_file_on_parsed_content():
    small = TestClient(create_app(Limits(max_upload_bytes=50)))
    assert_safe_error(upload(small, "/api/analyze", "a\n" + "1\n" * 30), 413, "file_too_large")


def test_large_upload_is_never_spooled_to_disk(monkeypatch):
    def forbid(self):
        raise AssertionError("upload rolled over to a temporary file")

    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "rollover", forbid)
    big_client = TestClient(create_app(Limits(max_upload_bytes=3_000_000, max_rows=400_000)))
    text = "a,b\n" + "1,2\n" * 400_000  # ~1.6 MB, above Starlette's 1 MB spool threshold
    response = upload(big_client, "/api/analyze", text)
    assert response.status_code == 200


def test_server_busy_returns_503(monkeypatch):
    app = create_app(TEST_LIMITS)
    app.state.analysis_slots.acquire()
    app.state.analysis_slots.acquire()  # both default slots taken
    monkeypatch.setattr(routes, "_BUSY_TIMEOUT_SECONDS", 0.01)
    assert_safe_error(upload(TestClient(app), "/api/analyze", GOOD), 503, "server_busy")


def test_unexpected_errors_are_generic_and_logs_hold_no_values(monkeypatch, caplog):
    def boom(*_args, **_kwargs):
        raise RuntimeError(f"failed while reading {SECRET}")

    monkeypatch.setattr(routes, "run_analysis", boom)
    client = TestClient(create_app(TEST_LIMITS), raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR):
        response = upload(client, "/api/analyze", GOOD)
    assert_safe_error(response, 500, "internal_error")
    assert "RuntimeError" in caplog.text and SECRET not in caplog.text


def test_security_headers_and_csp(client):
    for path in ("/", "/api/health"):
        headers = client.get(path).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert "script-src 'self'" in headers["content-security-policy"]


def test_csp_dev_live_allowance_is_opt_in_and_loopback_only():
    from app.main import build_csp

    default = build_csp(None)
    assert "script-src 'self';" in default and "connect-src 'self';" in default
    assert "style-src 'self';" in default and "unsafe-inline" not in default
    dev = build_csp("http://localhost:8400")
    assert "script-src 'self' http://localhost:8400;" in dev
    assert "connect-src 'self' http://localhost:8400;" in dev
    assert "style-src 'self' 'unsafe-inline';" in dev
    for bad in ("https://evil.example", "http://localhost:8400 'unsafe-eval'", "*", "http://10.0.0.5:8400"):
        with pytest.raises(RuntimeError):
            build_csp(bad)


def test_frontend_and_samples_are_served(client):
    assert "DataSentry" in client.get("/").text
    assert client.get("/app.js").status_code == 200
    assert client.get("/samples/customer_churn.csv").text.startswith("customer_id,")


@pytest.mark.parametrize("path", ["/../app/main.py", "/%2e%2e/app/main.py", "/samples/../app/main.py", "/samples/..%2fapp%2fmain.py"])
def test_static_paths_cannot_escape_their_directories(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert "create_app" not in response.text


def test_unknown_api_route_uses_error_schema(client):
    assert_safe_error(client.get("/api/nope"), 404, "http_error")


# --- Reports ---------------------------------------------------------------------------------


@pytest.mark.parametrize("fmt, media", [("json", "application/json"), ("html", "text/html; charset=utf-8")])
def test_report_downloads(client, fmt, media):
    response = upload(client, "/api/report", GOOD, filename="../../evil name.csv", format=fmt, target_column="label")
    assert response.status_code == 200
    assert response.headers["content-type"] == media
    assert response.headers["content-disposition"] == f'attachment; filename="datasentry-report-evil_name.{fmt}"'
    if fmt == "json":
        doc = json.loads(response.text)
        assert doc["analysis"]["settings"]["target_column"] == "label"
        assert doc["metadata"]["include_value_examples"] is False
    else:
        assert response.text.startswith("<!doctype html>")


def test_report_value_inclusion_flag(client):
    off = upload(client, "/api/report", GOOD, format="json").json()
    on = upload(client, "/api/report", GOOD, format="json", include_values="true").json()
    group = lambda doc: next(c for c in doc["analysis"]["columns"] if c["name"] == "group")  # noqa: E731
    assert group(off)["categorical"]["top_values"] == []
    assert [v["value"] for v in group(on)["categorical"]["top_values"]] == ["a", "b"]


@pytest.mark.parametrize("fields, code", [({"format": "pdf"}, "invalid_request"), ({"include_values": "maybe"}, "invalid_request")])
def test_report_rejects_bad_options(client, fields, code):
    assert_safe_error(upload(client, "/api/report", GOOD, **fields), 422, code)


# --- ML endpoints ----------------------------------------------------------------------------


def test_label_review_endpoint(client):
    body = upload(client, "/api/label-review", GOOD, target_column="label").json()
    assert body["status"] == "completed" and body["cv_folds"] == 5


def test_label_review_requires_target(client):
    assert_safe_error(upload(client, "/api/label-review", GOOD), 422, "missing_target_column")


def test_train_test_overlap_endpoint(client):
    test_text = "id,score,group,label\n0,0.0,a,n\n999,1.0,b,n\n"
    response = client.post(
        "/api/train-test-overlap",
        files={"train_file": ("train.csv", GOOD.encode()), "test_file": ("test.csv", test_text.encode())},
        data={"target_column": "label"},
    )
    body = response.json()
    assert response.status_code == 200 and body["n_test_rows_in_train"] == 1


def test_train_test_overlap_needs_both_files(client):
    response = client.post("/api/train-test-overlap", files={"train_file": ("a.csv", GOOD.encode())})
    assert_safe_error(response, 422, "missing_file")


def test_corrections_endpoint_requires_approval_and_applies_to_copy(client):
    data = GOOD + GOOD.splitlines()[1] + "\n"
    plan = {"approved": False, "steps": [{"operation": "drop_duplicate_rows"}]}
    assert_safe_error(upload(client, "/api/corrections/apply", data, plan=json.dumps(plan)), 422, "approval_required")
    plan["approved"] = True
    body = upload(client, "/api/corrections/apply", data, plan=json.dumps(plan)).json()
    assert body["audit"]["input"]["n_rows"] == 41 and body["audit"]["output"]["n_rows"] == 40
    assert body["csv"].splitlines()[0] == "id,score,group,label"


@pytest.mark.parametrize("plan", ["", "not json", json.dumps({"approved": True, "steps": []}), json.dumps({"approved": True, "steps": [{"operation": "rm -rf"}]})])
def test_corrections_endpoint_rejects_invalid_plans(client, plan):
    assert_safe_error(upload(client, "/api/corrections/apply", GOOD, plan=plan), 422, "invalid_plan")
