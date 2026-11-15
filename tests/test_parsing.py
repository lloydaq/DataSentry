"""Configurable parsing: delimiter, encoding and extra missing-value tokens."""

import json

import pytest

from app.services import loader
from app.services.loader import DatasetError, ParseOptions, load_csv, load_csv_as_text, parse_options
from tests.conftest import TEST_LIMITS, upload
from tests.test_api import SECRET, assert_safe_error

LATIN1 = "name;city;value\nJosé;Málaga;1\nZoë;Köln;2\n".encode("latin-1")


def read(raw: bytes, **options) -> loader.LoadedDataset:
    return load_csv(raw, TEST_LIMITS, "data.csv", parse_options(**options))


# --- Option parsing -----------------------------------------------------------------------------


def test_defaults_match_the_previous_behaviour():
    assert parse_options() == ParseOptions(delimiter="comma", encoding="utf-8", missing_values=())
    assert parse_options("", "  ", "") == ParseOptions()


def test_option_names_are_case_and_whitespace_insensitive():
    options = parse_options(" Semicolon ", "LATIN-1", None)
    assert (options.delimiter, options.encoding) == ("semicolon", "latin-1")


def test_missing_value_tokens_are_trimmed_deduplicated_and_ordered():
    options = parse_options(missing_values=" ? , -999,,?, n/a ")
    assert options.missing_values == ("?", "-999", "n/a")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"delimiter": ","},  # the character itself is not an accepted name
        {"delimiter": "space"},
        {"delimiter": "regex:.*"},
        {"encoding": "utf-16"},
        {"encoding": "cp1252"},
        {"missing_values": ",".join(f"t{i}" for i in range(loader.MAX_MISSING_VALUE_TOKENS + 1))},
        {"missing_values": "x" * (loader.MAX_MISSING_VALUE_TOKEN_LENGTH + 1)},
        {"missing_values": "bad\ttoken"},
        {"missing_values": "bell\x07"},
    ],
)
def test_invalid_options_are_rejected_with_a_fixed_message(kwargs):
    with pytest.raises(DatasetError) as info:
        parse_options(**kwargs)
    assert info.value.code == "invalid_request"
    for value in kwargs.values():
        if len(value) > 3:
            assert value not in info.value.message


def test_limits_are_inclusive():
    tokens = ",".join(f"t{i}" for i in range(loader.MAX_MISSING_VALUE_TOKENS))
    assert len(parse_options(missing_values=tokens).missing_values) == loader.MAX_MISSING_VALUE_TOKENS
    long = "x" * loader.MAX_MISSING_VALUE_TOKEN_LENGTH
    assert parse_options(missing_values=long).missing_values == (long,)


# --- Delimiters ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "sep"), [("comma", ","), ("semicolon", ";"), ("tab", "\t"), ("pipe", "|")]
)
def test_each_delimiter_parses_the_same_table(name, sep):
    raw = sep.join(["a", "b", "c"]) + "\n" + sep.join(["1", "x", "2.5"]) + "\n"
    frame = read(raw.encode(), delimiter=name).frame
    assert list(frame.columns) == ["a", "b", "c"]
    assert frame.iloc[0].tolist() == [1, "x", 2.5]


def test_semicolon_file_read_as_comma_is_one_column():
    # Without the option the file still loads, as a single column; the option fixes it.
    raw = b"a;b\n1;2\n"
    assert read(raw).frame.shape == (1, 1)
    assert read(raw, delimiter="semicolon").frame.shape == (1, 2)


def test_quoted_delimiters_stay_inside_fields():
    frame = read(b'a;b\n"x;y";2\n', delimiter="semicolon").frame
    assert frame.iloc[0].tolist() == ["x;y", 2]


def test_ragged_rows_are_still_rejected_with_a_custom_delimiter():
    with pytest.raises(DatasetError) as info:
        read(b"a|b\n1|2|3\n", delimiter="pipe")
    assert info.value.code == "malformed_csv"


def test_duplicate_headers_are_detected_with_a_custom_delimiter():
    with pytest.raises(DatasetError) as info:
        read(b"a\ta\n1\t2\n", delimiter="tab")
    assert info.value.code == "duplicate_header"


# --- Encodings ----------------------------------------------------------------------------------


def test_latin1_file_fails_as_utf8_with_a_helpful_hint():
    with pytest.raises(DatasetError) as info:
        read(LATIN1, delimiter="semicolon")
    assert info.value.code == "invalid_encoding"
    assert "Latin-1" in info.value.message
    assert "Jos" not in info.value.message


def test_latin1_option_decodes_accented_text():
    frame = read(LATIN1, delimiter="semicolon", encoding="latin-1").frame
    assert frame["name"].tolist() == ["José", "Zoë"]
    assert frame["city"].tolist() == ["Málaga", "Köln"]


def test_utf8_bom_is_still_accepted():
    frame = read("﻿a;b\n1;2\n".encode("utf-8"), delimiter="semicolon").frame
    assert list(frame.columns) == ["a", "b"]


def test_binary_files_are_rejected_even_as_latin1():
    with pytest.raises(DatasetError) as info:
        read(b"PK\x03\x04rest", encoding="latin-1")
    assert info.value.code == "unsupported_format"


# --- Missing-value tokens -----------------------------------------------------------------------


def test_custom_tokens_become_missing_and_defaults_still_apply():
    raw = b"a,b,c\n?,1,NA\nx,-999,\ny,3,z\n"
    frame = read(raw, missing_values="?,-999").frame
    assert frame["a"].isna().tolist() == [True, False, False]
    assert frame["b"].isna().tolist() == [False, True, False]
    assert frame["c"].isna().tolist() == [True, True, False]


def test_tokens_turn_a_sentinel_numeric_column_numeric():
    raw = b"v\n1\n-999\n3\n"
    frame = read(raw, missing_values="-999").frame
    assert frame["v"].isna().sum() == 1
    assert frame["v"].dropna().tolist() == [1, 3]


def test_tokens_match_whole_cells_exactly():
    frame = read(b"a\n?\n??\n ?\nwhat?\n", missing_values="?").frame
    assert frame["a"].isna().tolist() == [True, False, False, False]


def test_text_reread_keeps_original_cells_and_uses_the_same_delimiter():
    options = parse_options(delimiter="semicolon", encoding="latin-1", missing_values="?")
    text = load_csv_as_text(b"a;b\n?;Jos\xe9\n", options)
    assert text.iloc[0].tolist() == ["?", "José"]


# --- API ----------------------------------------------------------------------------------------


def test_analyze_echoes_the_options_used(client):
    body = upload(
        client, "/api/analyze", LATIN1, delimiter="semicolon", encoding="latin-1", missing_values="Köln, ?"
    ).json()
    assert body["dataset"]["n_columns"] == 3
    assert body["dataset"]["parsing"] == {
        "delimiter": "semicolon",
        "encoding": "latin-1",
        "missing_values": ["Köln", "?"],
    }
    city = next(c for c in body["columns"] if c["name"] == "city")
    assert city["n_missing"] == 1


def test_analyze_defaults_are_echoed(client):
    body = upload(client, "/api/analyze", "a,b\n1,2\n").json()
    assert body["dataset"]["parsing"] == {"delimiter": "comma", "encoding": "utf-8", "missing_values": []}


@pytest.mark.parametrize(
    "fields",
    [
        {"delimiter": "colon"},
        {"encoding": "ebcdic"},
        {"missing_values": SECRET + "x" * 40},
    ],
)
def test_invalid_options_fail_safely_over_http(client, fields):
    assert_safe_error(upload(client, "/api/analyze", "a,b\n1,2\n", **fields), 422, "invalid_request")


def test_every_upload_endpoint_honours_the_options(client):
    text = "id;score;label\n" + "".join(f"{i};{i * 2};{'yn'[i % 2]}\n" for i in range(40))
    opts = {"delimiter": "semicolon", "target_column": "label"}

    report = upload(client, "/api/report", text, format="json", **opts).json()
    assert report["analysis"]["dataset"]["parsing"]["delimiter"] == "semicolon"

    html = upload(client, "/api/report", text, format="html", **opts).text
    assert "semicolon-delimited" in html

    review = upload(client, "/api/label-review", text, **opts)
    assert review.status_code == 200, review.text

    overlap = client.post(
        "/api/train-test-overlap",
        files={"train_file": ("a.csv", text.encode()), "test_file": ("b.csv", "id;score;label\n0;0;y\n".encode())},
        data=opts,
    ).json()
    assert overlap["n_test_rows_in_train"] == 1
    assert overlap["train"]["parsing"]["delimiter"] == overlap["test"]["parsing"]["delimiter"] == "semicolon"

    plan = {"approved": True, "steps": [{"operation": "drop_duplicate_rows"}]}
    fixed = upload(client, "/api/corrections/apply", text + "0;0;y\n", plan=json.dumps(plan), **opts).json()
    assert fixed["audit"]["output"]["n_rows"] == 40
    assert fixed["csv"].splitlines()[0] == "id,score,label"  # output is always comma-separated UTF-8


def test_html_report_escapes_missing_value_tokens(client):
    html = upload(client, "/api/report", "a\n1\n", format="html", missing_values="<b>x</b>").text
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html


def test_options_do_not_change_the_dataset_hash(client):
    plain = upload(client, "/api/analyze", "a;b\n1;2\n").json()
    split = upload(client, "/api/analyze", "a;b\n1;2\n", delimiter="semicolon").json()
    assert plain["dataset"]["sha256"] == split["dataset"]["sha256"]
