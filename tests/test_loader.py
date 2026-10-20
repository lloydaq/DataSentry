import pytest

from app.config import Limits
from app.services.loader import DatasetError, load_csv, sanitize_filename
from tests.conftest import TEST_LIMITS, load


def error_of(raw: bytes, filename: str | None = "data.csv", limits: Limits = TEST_LIMITS) -> DatasetError:
    with pytest.raises(DatasetError) as info:
        load_csv(raw, limits, filename)
    return info.value


def test_valid_csv_is_parsed_with_types():
    dataset = load("a,b,c\n1,x,1.5\n2,y,\n")
    frame = dataset.frame
    assert frame.shape == (2, 3)
    assert list(frame.columns) == ["a", "b", "c"]
    assert frame["a"].tolist() == [1, 2]
    assert frame["c"].isna().tolist() == [False, True]
    assert dataset.size_bytes == len(b"a,b,c\n1,x,1.5\n2,y,\n")
    assert len(dataset.sha256) == 64


def test_utf8_bom_is_stripped_from_first_header():
    dataset = load_csv("\ufeffname,value\nx,1\n".encode("utf-8"), TEST_LIMITS, "d.csv")
    assert list(dataset.frame.columns) == ["name", "value"]


def test_unicode_and_markup_headers_are_kept_verbatim():
    header = 'température,名前,"<script>alert(1)</script>"'
    dataset = load(f"{header}\n1,2,3\n")
    assert list(dataset.frame.columns) == ["température", "名前", "<script>alert(1)</script>"]


def test_quoted_fields_with_commas_and_newlines():
    dataset = load('a,b\n"x, y","line1\nline2"\n')
    assert dataset.frame.iloc[0].tolist() == ["x, y", "line1\nline2"]


def test_blank_lines_are_skipped_consistently():
    dataset = load("a,b\n1,2\n\n3,4\n")
    assert dataset.frame.shape == (2, 2)


@pytest.mark.parametrize(
    "raw, code",
    [
        (b"", "empty_file"),
        (b"\n\n", "empty_file"),
        (b"a,b\n", "no_data_rows"),
        (b"a,a\n1,2\n", "duplicate_header"),
        (b"a,,c\n1,2,3\n", "empty_header"),
        (b"a, \n1,2\n", "empty_header"),
        (b"a,b\n1,2,3\n", "malformed_csv"),
        (b"a,b\n1\n", "malformed_csv"),
        (b'a,b\n"1,2\n', "malformed_csv"),
        (b"a,b\n\xff\xfe,1\n", "invalid_encoding"),
        (b"a,b\n1,\x002\n", "unsupported_format"),
        (b"PK\x03\x04rest", "unsupported_format"),
        (b"%PDF-1.7", "unsupported_format"),
    ],
)
def test_invalid_inputs_raise_controlled_errors(raw, code):
    assert error_of(raw).code == code


def test_duplicate_header_detected_before_pandas_renames():
    err = error_of(b"id,name,id\n1,a,2\n")
    assert err.code == "duplicate_header"
    assert "1 and 3" in err.message


def test_unsupported_extension_is_rejected():
    err = error_of(b"a\n1\n", filename="data.xlsx")
    assert (err.code, err.status_code) == ("unsupported_format", 415)


def test_missing_filename_is_allowed():
    assert load_csv(b"a\n1\n", TEST_LIMITS, None).filename == "dataset.csv"


def test_size_limit():
    limits = Limits(max_upload_bytes=10)
    err = error_of(b"a,b\n1,2\n3,4\n", limits=limits)
    assert (err.code, err.status_code) == ("file_too_large", 413)


def test_row_limit_stops_early():
    limits = Limits(max_rows=3)
    raw = b"a\n" + b"1\n" * 4
    assert error_of(raw, limits=limits).code == "too_many_rows"
    assert load_csv(b"a\n" + b"1\n" * 3, limits, "d.csv").frame.shape == (3, 1)


def test_column_limit():
    limits = Limits(max_columns=3)
    assert error_of(b"a,b,c,d\n1,2,3,4\n", limits=limits).code == "too_many_columns"


def test_error_messages_never_contain_cell_values():
    secret = "SECRET-CELL-9481"
    for raw in (
        f"a,b\n{secret},1,2\n".encode(),
        f'a,b\n"{secret},1\n'.encode(),
        f"a,b\n{secret}\n".encode(),
    ):
        assert secret not in error_of(raw).message


def test_oversized_field_is_rejected_as_malformed():
    raw = b"a,b\n" + b"x" * 200_000 + b",1\n"
    assert error_of(raw, limits=Limits()).code == "malformed_csv"


@pytest.mark.parametrize(
    "given, expected",
    [
        ("../../etc/passwd.csv", "passwd.csv"),
        (r"C:\Users\me\data.csv", "data.csv"),
        ("my data (final).csv", "my_data_final_.csv"),
        ("", "dataset.csv"),
        (None, "dataset.csv"),
        ("....", "dataset.csv"),
        ("<img src=x onerror=alert(1)>.csv", "img_src_x_onerror_alert_1_.csv"),
    ],
)
def test_sanitize_filename(given, expected):
    assert sanitize_filename(given) == expected
