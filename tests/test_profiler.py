import io

import numpy as np
import pandas as pd
import pytest

from app.models.schemas import InferredType
from app.services import profiler
from tests.conftest import load, rows_csv


def frame(text: str) -> pd.DataFrame:
    return load(text).frame


def profile(text: str, column: str):
    return next(p for p in profiler.profile_columns(frame(text)) if p.name == column)


@pytest.mark.parametrize(
    "values, expected",
    [
        (["1", "2", "3"], InferredType.numeric),
        (["1.5", "", "3"], InferredType.numeric),
        (["True", "False", "True"], InferredType.boolean),
        (["true", "", "FALSE"], InferredType.boolean),
        (["2024-01-01", "2024-02-03T10:00:00", ""], InferredType.datetime),
        (["01/02/2024", "03/04/2024", "05/06/2024"], InferredType.categorical),
        (["red", "blue", "red"], InferredType.categorical),
        (["", "", ""], InferredType.empty),
    ],
)
def test_type_inference(values, expected):
    # A second column keeps rows of a single empty cell from being read as blank lines.
    assert profile(rows_csv("x,k", [f"{v},1" for v in values]), "x").inferred_type is expected


def test_high_cardinality_strings_are_text():
    values = [f"comment number {i}" for i in range(120)]
    assert profile(rows_csv("x", values), "x").inferred_type is InferredType.text


def test_missing_value_counts_and_tokens():
    p = profile("x,y\n1,a\n,b\nNA,c\nnull,d\n", "x")
    assert (p.n_missing, p.missing_fraction, p.n_non_null) == (3, 0.75, 1)
    assert not p.all_missing


def test_all_missing_column():
    p = profile("x,y\n,1\n,2\n", "x")
    assert p.all_missing and p.inferred_type is InferredType.empty
    assert not p.is_constant  # reported as all-missing instead of constant
    assert p.unique_fraction is None and p.dominant_fraction is None


def test_constant_column_with_and_without_missing():
    assert profile("x,y\n5,1\n5,2\n5,3\n", "x").is_constant
    with_missing = profile("x,y\n5,1\n,2\n5,3\n", "x")
    assert with_missing.is_constant and with_missing.n_missing == 1
    assert not profile("x,y\n5,1\n6,2\n", "x").is_constant


def test_numeric_stats_exclude_infinity_and_handle_small_samples():
    p = profile("x\n1\n2\ninf\n-inf\n\n4\n", "x")
    n = p.numeric
    assert (n.n_finite, n.n_infinite) == (3, 2)
    assert (n.min, n.max, n.median) == (1.0, 4.0, 2.0)
    assert n.mean == pytest.approx(7 / 3, abs=1e-6)
    assert n.outliers.status == "unavailable"  # fewer than 10 finite values


def test_single_value_has_no_std():
    n = profile("x\n7\n", "x").numeric
    assert n.std is None and n.mean == 7.0


def test_all_infinite_column_has_null_statistics():
    n = profile("x\ninf\ninf\n", "x").numeric
    assert n.n_finite == 0 and n.min is None and n.mean is None and n.median is None


def test_iqr_outliers():
    values = [str(v) for v in range(1, 21)] + ["1000"]
    o = profile(rows_csv("x", values), "x").numeric.outliers
    assert o.status == "computed"
    assert (o.n_below, o.n_above) == (0, 1)
    assert o.upper_fence == pytest.approx(31.0)


def test_iqr_zero_is_unavailable_not_all_outliers():
    values = ["5"] * 15 + ["6", "100"]
    o = profile(rows_csv("x", values), "x").numeric.outliers
    assert o.status == "unavailable" and "interquartile" in o.reason


def test_categorical_stats_ordering_variants_and_whitespace():
    values = ["b", "a", "a", "Yes", "yes ", "YES", "b", "c"]
    s = profile(rows_csv("x", values), "x").categorical
    assert [v.value for v in s.top_values[:2]] == ["a", "b"]  # ties broken alphabetically
    assert s.n_unique == 6
    assert s.n_variant_groups == 1
    assert s.variant_groups[0].variants == ["YES", "Yes", "yes "]
    assert s.n_whitespace_values == 1


def test_top_values_are_truncated_and_clipped():
    values = [f"v{i:03d}" for i in range(30)] + ["x" * 500]
    s = profile(rows_csv("x", values), "x").categorical
    assert len(s.top_values) == profiler.TOP_VALUES_LIMIT and s.top_values_truncated
    long = profile(rows_csv("x", ["x" * 500] * 2 + ["y"]), "x").categorical.top_values[0].value
    assert len(long) == profiler.MAX_VALUE_LENGTH


def test_rare_categories_only_with_enough_rows():
    few = profile(rows_csv("x", ["a"] * 50 + ["b"]), "x").categorical
    assert few.n_rare_categories is None
    many = profile(rows_csv("x", ["a"] * 200 + ["b"]), "x").categorical
    assert many.n_rare_categories == 1


def test_identifier_like():
    ids = [f"{i}" for i in range(30)]
    assert profile(rows_csv("id", ids), "id").identifier_like
    assert not profile(rows_csv("id", ids[:10]), "id").identifier_like  # too few rows
    floats = [f"{i}.5" for i in range(30)]
    assert not profile(rows_csv("x", floats), "x").identifier_like


def test_overview_counts():
    df = frame("a,b\n1,\n,\n3,4\n")
    o = profiler.overview(df, profiler.profile_columns(df))
    assert (o.n_cells, o.n_missing_cells, o.n_rows_with_missing) == (6, 3, 2)
    assert o.missing_cell_fraction == 0.5
    assert {t.inferred_type: t.n_columns for t in o.type_counts}[InferredType.numeric] == 2
    assert profiler.overview(df, None).type_counts is None


def test_duplicate_rows_count_repeats_only_and_treat_missing_as_equal():
    df = frame("a,b\n1,x\n1,x\n2,\n2,\n1,x\n3,y\n")
    d = profiler.duplicate_rows(df)
    assert d.n_duplicate_rows == 3
    assert d.n_duplicate_groups == 2
    assert d.example_row_indices == [1, 3, 4]
    assert d.duplicate_fraction == 0.5


def test_duplicates_compare_parsed_values():
    df = frame("a,b\n1,x\n1.0,x\n")
    assert profiler.duplicate_rows(df).n_duplicate_rows == 1


def test_no_duplicates():
    assert profiler.duplicate_rows(frame("a\n1\n2\n")).n_duplicate_rows == 0


def test_redundancy_identical_and_correlated_columns():
    rng = np.random.default_rng(0)
    x = rng.normal(size=40)
    df = pd.DataFrame({"a": x, "b": x, "c": x * 2 + 1, "d": rng.normal(size=40), "k": 1})
    df.loc[3, "c"] = np.inf  # infinity must not break correlation screening
    red = profiler.redundancy(df, profiler.profile_columns(df))
    assert red.duplicate_column_groups == [["a", "b"]]
    pairs = {(p.column_a, p.column_b) for p in red.correlated_pairs}
    assert pairs == {("a", "c")}
    assert red.correlated_pairs[0].n_pairs == 39


def test_correlation_screening_skipped_above_column_limit():
    rng = np.random.default_rng(1)
    df = pd.DataFrame(rng.normal(size=(20, profiler.CORRELATION_MAX_COLUMNS + 1)))
    df.columns = [f"c{i}" for i in range(df.shape[1])]
    red = profiler.redundancy(df, profiler.profile_columns(df))
    assert red.correlation_status == "skipped" and red.correlation_note


def test_profiling_is_deterministic():
    text = io.StringIO()
    rng = np.random.default_rng(3)
    pd.DataFrame(
        {"n": rng.normal(size=200), "c": rng.choice(["a", "b", "c"], 200), "i": range(200)}
    ).to_csv(text, index=False)
    first = [p.model_dump_json() for p in profiler.profile_columns(frame(text.getvalue()))]
    second = [p.model_dump_json() for p in profiler.profile_columns(frame(text.getvalue()))]
    assert first == second
