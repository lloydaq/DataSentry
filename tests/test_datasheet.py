"""Datasheet draft: every filled field traces to the analysis; person-only questions stay empty."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import cli
from app.services import datasheet, profiler
from app.services.analysis import run_analysis
from app.services.loader import load_csv
from tests.conftest import TEST_LIMITS, load, rows_csv, upload
from tests.test_api import SECRET, assert_safe_error

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"
FIXED = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
PERSON_ONLY = {"Motivation", "Collection process", "Preprocessing, cleaning and labeling", "Uses",
               "Distribution and maintenance"}


def sample(name: str, target: str | None):
    result = run_analysis(load_csv((SAMPLES / name).read_bytes(), TEST_LIMITS, name), target)
    return result, datasheet.build_datasheet(result, FIXED)


def resolve(doc, path: str):
    """Follow a source path such as 'columns[3].missing_fraction' through the result JSON."""
    node = doc
    for name, index in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)(?:\[(\d+)\])?", path):
        node = node[name]
        if index:
            node = node[int(index)]
    return node


def traces(raw, value: str) -> bool:
    if isinstance(raw, bool):
        return str(raw).lower() in value.lower()
    if isinstance(raw, float):
        return value in (f"{raw:.1%}", f"{raw:g}") or f"{raw:g}" in value
    if isinstance(raw, int):
        return str(raw) in value
    if isinstance(raw, str):
        return raw == value or raw in value
    if isinstance(raw, list):
        return ", ".join(map(str, raw)) == value
    if isinstance(raw, dict):  # a finding or a class count: its own text or numbers appear in the value
        return (raw.get("explanation", "\0") in value) or (
            str(raw.get("count")) in value and f"{raw.get('fraction', 0):.1%}" in value)
    return False


# --- Traceability -------------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "target"), [("customer_churn.csv", "churned"), ("sensor_energy.csv", "energy_kwh"),
                                              ("customer_churn.csv", None)])
def test_every_filled_field_traces_to_the_analysis_result(name, target):
    result, sheet = sample(name, target)
    doc = json.loads(result.model_dump_json())
    fields = [f for s in sheet.sections for f in s.fields]
    assert fields
    for f in fields:
        raw = resolve(doc, f.source)
        assert traces(raw, f.value), (f.source, raw, f.value)


def test_per_column_fields_cover_every_column_and_name_it():
    result, sheet = sample("customer_churn.csv", "churned")
    composition = next(s for s in sheet.sections if s.title == "Composition")
    groups = {f.group for f in composition.fields if f.group}
    assert groups == {c.name for c in result.columns}
    for f in composition.fields:
        if f.group:
            index = int(re.search(r"columns\[(\d+)\]", f.source).group(1))
            assert result.columns[index].name == f.group


def test_known_issues_list_problems_but_not_observations():
    result, sheet = sample("customer_churn.csv", "churned")
    issues = next(s for s in sheet.sections if s.title == "Known data-quality findings")
    listed = {f.source for f in issues.fields if f.source.startswith("findings[")}
    expected = {f"findings[{i}]" for i, f in enumerate(result.findings) if f.kind.value != "observation"}
    assert listed == expected
    assert "observation(s)" in issues.note


# --- Person-only content stays empty ------------------------------------------------------------


def test_questions_are_always_unanswered_and_person_sections_have_no_facts():
    for name, target in [("customer_churn.csv", "churned"), ("sensor_energy.csv", None)]:
        _, sheet = sample(name, target)
        for section in sheet.sections:
            assert all(q.answer is None for q in section.questions)
            if section.title in PERSON_ONLY:
                assert section.filled_by == "person" and section.fields == []
        assert "does not know who created" in sheet.disclaimer


def test_markdown_leaves_a_blank_for_every_question():
    _, sheet = sample("customer_churn.csv", "churned")
    text = datasheet.render_markdown(sheet)
    n_questions = sum(len(s.questions) for s in sheet.sections)
    assert text.count("_To be completed by a person._") == n_questions
    for section in sheet.sections:
        for q in section.questions:
            block = text.split(f"**{q.question}**", 1)[1]
            assert block.lstrip().startswith("_To be completed by a person._")


def test_answer_cannot_be_set_on_a_question():
    from pydantic import ValidationError

    from app.models.schemas import DatasheetQuestion

    with pytest.raises(ValidationError):
        DatasheetQuestion(question="Why?", answer="Because we said so")


# --- Target variants and partial analyses -------------------------------------------------------


def test_no_target_asks_instead_of_guessing():
    _, sheet = sample("customer_churn.csv", None)
    target = next(s for s in sheet.sections if s.title == "Target")
    assert target.fields == [] and target.filled_by == "person"
    assert "No target column was selected" in target.note


def test_regression_target_reports_its_distribution():
    _, sheet = sample("sensor_energy.csv", "energy_kwh")
    labels = {f.label for f in next(s for s in sheet.sections if s.title == "Target").fields}
    assert {"Task", "Min", "Median", "Mean", "Max"} <= labels


def test_partial_analysis_is_said_not_hidden(monkeypatch):
    def broken(frame):
        raise RuntimeError("boom")

    monkeypatch.setattr(profiler, "profile_columns", broken)
    sheet = datasheet.build_datasheet(run_analysis(load("a,b\n1,2\n")), FIXED)
    composition = next(s for s in sheet.sections if s.title == "Composition")
    assert "did not complete" in composition.note
    assert not any(f.group for f in composition.fields)


def test_draft_is_deterministic_for_a_fixed_timestamp():
    result, _ = sample("customer_churn.csv", "churned")
    assert datasheet.render_markdown(datasheet.build_datasheet(result, FIXED)) == \
        datasheet.render_markdown(datasheet.build_datasheet(result, FIXED))


# --- Markdown safety ----------------------------------------------------------------------------


def test_md_escapes_markup_and_flattens_lines():
    assert datasheet.md("a*b_c`d") == "a\\*b\\_c\\`d"
    assert datasheet.md("[x](javascript:alert(1))") == "\\[x\\]\\(javascript:alert\\(1\\)\\)"
    assert datasheet.md("<img src=x>") == "\\<img src=x\\>"
    assert datasheet.md("line1\nline2\r\n  line3") == "line1 line2 line3"
    assert datasheet.md("5.8% - ok") == "5.8% - ok"


def test_crafted_column_names_cannot_inject_markdown_or_break_the_table():
    names = ['"[click](javascript:alert(1))"', '"<img src=x onerror=alert(1)>"', '"a|b"', '"# heading"']
    text = rows_csv(",".join(names), [",".join(str(i + j) for j in range(4)) for i in range(25)])
    md_text = datasheet.render_markdown(datasheet.build_datasheet(run_analysis(load(text)), FIXED))
    # Only escaped forms may appear: no unescaped link syntax or HTML tag.
    assert not re.search(r"(?<!\\)\[click", md_text)
    assert not re.search(r"(?<!\\)<img", md_text)
    assert r"\<img" in md_text and r"\[click\]\(" in md_text
    table = [line for line in md_text.splitlines() if line.startswith("| ") and "javascript" in line]
    assert len(table) == 1
    unescaped_pipes = len(re.findall(r"(?<!\\)\|", table[0]))
    assert unescaped_pipes == 5  # 4 cells: Column, Type, Missing, Distinct values


# --- API and CLI --------------------------------------------------------------------------------


def test_datasheet_endpoint_returns_markdown_by_default(client):
    text = (SAMPLES / "customer_churn.csv").read_text(encoding="utf-8")
    response = upload(client, "/api/datasheet", text, filename="customer_churn.csv", target_column="churned")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert 'filename="datasentry-datasheet-customer_churn.md"' in response.headers["content-disposition"]
    assert response.text.startswith("# Datasheet draft: customer\\_churn.csv")


def test_datasheet_endpoint_json_and_parsing_options(client):
    text = rows_csv("a;b", [f"{i};{i % 3}" for i in range(30)])
    body = upload(client, "/api/datasheet", text, format="json", delimiter="semicolon").json()
    composition = next(s for s in body["sections"] if s["title"] == "Composition")
    assert {f["label"]: f["value"] for f in composition["fields"] if not f["group"]}["Delimiter"] == "semicolon"


def test_datasheet_endpoint_errors_are_safe(client):
    assert_safe_error(upload(client, "/api/datasheet", "a\n1\n", format="pdf"), 422, "invalid_request")
    assert_safe_error(upload(client, "/api/datasheet", "a\n1\n", target_column=SECRET), 422, "unknown_target_column")


def test_cli_writes_a_datasheet(tmp_path, capsys):
    data = tmp_path / "data.csv"
    data.write_bytes(rows_csv("x,y", [f"{i},{'ab'[i % 2]}" for i in range(30)]).encode())
    out = tmp_path / "sheet.md"
    code = cli.main(["check", str(data), "--datasheet", str(out), "--fail-on", "never"])
    assert code == 0 and "Datasheet draft written" in capsys.readouterr().out
    assert out.read_text(encoding="utf-8").startswith("# Datasheet draft: data.csv")
    assert cli.main(["check", str(data), "--datasheet", str(tmp_path / "sheet.txt")]) == cli.EXIT_USAGE
