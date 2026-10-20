import json
from datetime import UTC, datetime

from app.services import report
from app.services.analysis import run_analysis
from tests.conftest import load

XSS = "<script>alert('x')</script>"
DATA = (
    f'id,"{XSS}",plan,y\n'
    + "".join(f'{i},"<b>v{i % 3}</b>",{["Basic", "basic ", "Pro"][i % 3]},{"ab"[i % 2]}\n' for i in range(30))
)
FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def doc(include_values: bool = False):
    return report.build_report(run_analysis(load(DATA), "y"), include_values, FIXED)


def test_json_report_is_strict_and_complete():
    text = doc().model_dump_json()
    parsed = json.loads(text, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
    assert parsed["metadata"]["tool"] == "DataSentry"
    assert parsed["metadata"]["generated_at"] == "2026-01-01T00:00:00+00:00"
    assert parsed["analysis"]["settings"] == {"target_column": "y"}
    assert parsed["analysis"]["status"] == "complete"
    assert parsed["methodology"] and parsed["analysis"]["limitations"]


def test_values_are_redacted_by_default_and_original_result_untouched():
    result = run_analysis(load(DATA), "y")
    redacted = report.build_report(result, False, FIXED)
    plan = next(c for c in redacted.analysis.columns if c.name == "plan").categorical
    assert plan.top_values == [] and plan.variant_groups == [] and plan.values_redacted
    original = next(c for c in result.columns if c.name == "plan").categorical
    assert original.top_values and not original.values_redacted
    assert "Basic" not in redacted.model_dump_json()


def test_values_included_when_requested():
    assert "Basic" in doc(include_values=True).model_dump_json()


def test_report_generation_is_reproducible_for_fixed_time():
    assert doc().model_dump_json() == doc().model_dump_json()
    assert report.render_html(doc()) == report.render_html(doc())


def test_html_report_escapes_untrusted_content():
    html = report.render_html(doc(include_values=True))
    assert "<script>" not in html
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in html
    assert "<b>v" not in html
    assert "default-src 'none'" in html
    for section in ("Executive summary", "Dataset overview", "Findings", "Column diagnostics", "Methodology", "Limitations"):
        assert section in html


def test_html_report_handles_partial_results(monkeypatch):
    from app.services import profiler

    def boom(*_args):
        raise RuntimeError

    monkeypatch.setattr(profiler, "profile_columns", boom)
    d = report.build_report(run_analysis(load("a,b\n1,2\n")), False, FIXED)
    html = report.render_html(d)
    assert d.analysis.status == "partial" and "columns: failed" in html
