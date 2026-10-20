"""Deterministic dataset profiling: types, missing values, duplicates, column statistics.

Profiling reports observations only. Deciding which observations are potential problems is the
job of ``findings.py``.
"""

import math
import re

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

from app.models.schemas import (
    CategoricalStats,
    ColumnProfile,
    CorrelatedPair,
    DatetimeStats,
    DuplicateSummary,
    InferredType,
    NumericStats,
    OutlierSummary,
    Overview,
    RedundancySummary,
    TypeCount,
    ValueCount,
    VariantGroup,
)

# Documented thresholds (see README "Diagnostic methodology").
CATEGORICAL_MAX_UNIQUE = 50  # string columns with at most this many distinct values are categorical
CATEGORICAL_MAX_UNIQUE_FRACTION = 0.5  # ...or whose distinct/non-null ratio is at most this
TOP_VALUES_LIMIT = 10
VARIANT_GROUPS_LIMIT = 10
MAX_VALUE_LENGTH = 200  # displayed category values are clipped to this many characters
RARE_CATEGORY_FRACTION = 0.01
RARE_CATEGORY_MIN_ROWS = 100  # rare categories are only evaluated with this many non-null values
RARE_CATEGORY_MAX_UNIQUE = 1000
OUTLIER_MIN_VALUES = 10
IDENTIFIER_MIN_ROWS = 20
CORRELATION_THRESHOLD = 0.99
CORRELATION_MIN_PAIRS = 10
CORRELATION_MAX_COLUMNS = 50
DUPLICATE_EXAMPLES_LIMIT = 10

DUPLICATE_SEMANTICS = (
    "A duplicate row is an exact repeat of an earlier row across all columns, compared after "
    "parsing (so 1 and 1.0 in a numeric column are equal) and with missing values treated as "
    "equal to each other. The first occurrence is not counted; only the repeats are."
)

_BOOLEAN_TOKENS = frozenset({"true", "false"})
_ISO_DATETIME = re.compile(
    r"\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(Z|[+-]\d{2}:?\d{2})?)?"
)
_WHITESPACE_RUN = re.compile(r"\s+")


def finite(value: float | int | None, digits: int = 6) -> float | None:
    """Convert to a rounded finite float, mapping NaN, infinity and None to None."""
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return round(value, digits)


def fraction(part: int, whole: int) -> float:
    return round(part / whole, 6) if whole else 0.0


def clip(text: str) -> str:
    return text if len(text) <= MAX_VALUE_LENGTH else text[: MAX_VALUE_LENGTH - 1] + "…"


def as_text(series: pd.Series) -> pd.Series:
    """Non-null values of a non-numeric column as Python strings."""
    return series.dropna().astype(str)


def infer_type(series: pd.Series) -> InferredType:
    non_null = series.dropna()
    if non_null.empty:
        return InferredType.empty
    if ptypes.is_bool_dtype(series):
        return InferredType.boolean
    if ptypes.is_numeric_dtype(series):
        return InferredType.numeric
    if ptypes.is_datetime64_any_dtype(series):
        return InferredType.datetime
    if non_null.map(lambda v: isinstance(v, (bool, np.bool_))).all():
        return InferredType.boolean
    text = non_null.astype(str)
    if text.str.strip().str.lower().isin(_BOOLEAN_TOKENS).all():
        return InferredType.boolean
    if text.str.fullmatch(_ISO_DATETIME).all():
        return InferredType.datetime
    n_unique = text.nunique()
    if (
        n_unique <= CATEGORICAL_MAX_UNIQUE
        or n_unique / len(text) <= CATEGORICAL_MAX_UNIQUE_FRACTION
    ):
        return InferredType.categorical
    return InferredType.text


def numeric_values(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("float64").dropna()


def numeric_stats(series: pd.Series) -> NumericStats:
    values = numeric_values(series)
    arr = values.to_numpy()
    finite_mask = np.isfinite(arr)
    vals = arr[finite_mask]
    n = len(vals)
    if n == 0:
        quantiles = [None] * 5
    else:
        quantiles = [finite(q) for q in np.quantile(vals, [0.05, 0.25, 0.5, 0.75, 0.95])]
    with np.errstate(over="ignore", invalid="ignore"):
        mean = finite(vals.mean()) if n else None
        std = finite(vals.std(ddof=1)) if n >= 2 else None
    return NumericStats(
        n_finite=n,
        n_infinite=int((~finite_mask).sum()),
        min=finite(vals.min()) if n else None,
        max=finite(vals.max()) if n else None,
        mean=mean,
        median=quantiles[2],
        std=std,
        p05=quantiles[0],
        q1=quantiles[1],
        q3=quantiles[3],
        p95=quantiles[4],
        n_zeros=int((vals == 0).sum()),
        n_negative=int((vals < 0).sum()),
        all_integer=bool(n and np.all(np.mod(vals, 1) == 0)),
        outliers=_iqr_outliers(vals),
    )


def _iqr_outliers(vals: np.ndarray) -> OutlierSummary:
    if len(vals) < OUTLIER_MIN_VALUES:
        return OutlierSummary(
            status="unavailable",
            reason=f"Fewer than {OUTLIER_MIN_VALUES} finite values.",
        )
    q1, q3 = np.quantile(vals, [0.25, 0.75])
    iqr = q3 - q1
    if iqr == 0:
        return OutlierSummary(
            status="unavailable",
            reason="The interquartile range is zero (at least half the values are identical), "
            "so IQR fences cannot separate unusual values.",
        )
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    n_below, n_above = int((vals < lower).sum()), int((vals > upper).sum())
    return OutlierSummary(
        status="computed",
        lower_fence=finite(lower),
        upper_fence=finite(upper),
        n_below=n_below,
        n_above=n_above,
        fraction=fraction(n_below + n_above, len(vals)),
    )


def _normalize_category(value: str) -> str:
    return _WHITESPACE_RUN.sub(" ", value.strip()).casefold()


def categorical_stats(series: pd.Series, inferred: InferredType) -> CategoricalStats:
    text = as_text(series)
    n = len(text)
    counts = text.value_counts()
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    top = [
        ValueCount(value=clip(value), count=int(count), fraction=fraction(int(count), n))
        for value, count in ordered[:TOP_VALUES_LIMIT]
    ]

    n_rare: int | None = None
    rare_rows: float | None = None
    if n >= RARE_CATEGORY_MIN_ROWS and len(counts) <= RARE_CATEGORY_MAX_UNIQUE:
        rare = counts[counts / n < RARE_CATEGORY_FRACTION]
        n_rare = int(len(rare))
        rare_rows = fraction(int(rare.sum()), n)

    groups: dict[str, list[tuple[str, int]]] = {}
    if inferred in (InferredType.categorical, InferredType.boolean):
        for value, count in ordered:
            groups.setdefault(_normalize_category(value), []).append((value, int(count)))
    variant_groups = sorted(
        (
            VariantGroup(variants=sorted(clip(v) for v, _ in members), n_rows=sum(c for _, c in members))
            for members in groups.values()
            if len(members) > 1
        ),
        key=lambda g: (-g.n_rows, g.variants),
    )

    lengths = text.str.len()
    return CategoricalStats(
        n_unique=int(len(counts)),
        top_values=top,
        top_values_truncated=len(counts) > TOP_VALUES_LIMIT,
        n_rare_categories=n_rare,
        rare_rows_fraction=rare_rows,
        n_variant_groups=len(variant_groups),
        variant_groups=variant_groups[:VARIANT_GROUPS_LIMIT],
        n_whitespace_values=int((text != text.str.strip()).sum()),
        n_numeric_like=int(pd.to_numeric(text, errors="coerce").notna().sum()),
        mean_length=finite(lengths.mean(), 2) if n else None,
        max_length=int(lengths.max()) if n else None,
    )


def datetime_stats(series: pd.Series) -> DatetimeStats:
    text = as_text(series)
    parsed = pd.to_datetime(text, errors="coerce", format="ISO8601", utc=True)
    valid = parsed.dropna()
    return DatetimeStats(
        min=valid.min().isoformat() if len(valid) else None,
        max=valid.max().isoformat() if len(valid) else None,
        n_unparseable=int(parsed.isna().sum()),
    )


def profile_column(series: pd.Series, position: int) -> ColumnProfile:
    n_rows = len(series)
    inferred = infer_type(series)
    n_missing = int(series.isna().sum())
    n_non_null = n_rows - n_missing
    n_unique = int(series.nunique(dropna=True))
    dominant = None
    if n_non_null:
        dominant = fraction(int(series.value_counts(dropna=True).iloc[0]), n_non_null)

    numeric = categorical = dt = None
    if inferred is InferredType.numeric:
        numeric = numeric_stats(series)
    elif inferred is InferredType.datetime:
        dt = datetime_stats(series)
    elif inferred is not InferredType.empty:
        categorical = categorical_stats(series, inferred)

    identifier_like = (
        n_rows >= IDENTIFIER_MIN_ROWS
        and n_missing == 0
        and n_unique == n_rows
        and (
            inferred in (InferredType.categorical, InferredType.text)
            or (numeric is not None and numeric.all_integer and numeric.n_infinite == 0)
        )
    )

    return ColumnProfile(
        name=str(series.name),
        position=position,
        pandas_dtype=str(series.dtype),
        inferred_type=inferred,
        n_non_null=n_non_null,
        n_missing=n_missing,
        missing_fraction=fraction(n_missing, n_rows),
        all_missing=n_non_null == 0,
        n_unique=n_unique,
        unique_fraction=fraction(n_unique, n_non_null) if n_non_null else None,
        is_constant=n_non_null > 0 and n_unique == 1,
        dominant_fraction=dominant,
        identifier_like=identifier_like,
        numeric=numeric,
        categorical=categorical,
        datetime=dt,
    )


def profile_columns(frame: pd.DataFrame) -> list[ColumnProfile]:
    return [profile_column(frame.iloc[:, i], i) for i in range(frame.shape[1])]


def overview(frame: pd.DataFrame, profiles: list[ColumnProfile] | None) -> Overview:
    n_rows, n_cols = frame.shape
    missing = frame.isna()
    rows_with_missing = int(missing.any(axis=1).sum())
    type_counts = None
    if profiles is not None:
        counts = {t: 0 for t in InferredType}
        for p in profiles:
            counts[p.inferred_type] += 1
        type_counts = [TypeCount(inferred_type=t, n_columns=c) for t, c in counts.items()]
    n_cells = n_rows * n_cols
    n_missing = int(missing.to_numpy().sum())
    return Overview(
        n_rows=n_rows,
        n_columns=n_cols,
        memory_bytes=int(frame.memory_usage(deep=True, index=False).sum()),
        type_counts=type_counts,
        n_cells=n_cells,
        n_missing_cells=n_missing,
        missing_cell_fraction=fraction(n_missing, n_cells),
        n_rows_with_missing=rows_with_missing,
        rows_with_missing_fraction=fraction(rows_with_missing, n_rows),
    )


def duplicate_rows(frame: pd.DataFrame) -> DuplicateSummary:
    repeats = frame.duplicated(keep="first")
    n_dup = int(repeats.sum())
    n_groups = int(frame[frame.duplicated(keep=False) & ~repeats].shape[0])
    examples = np.flatnonzero(repeats.to_numpy())[:DUPLICATE_EXAMPLES_LIMIT]
    return DuplicateSummary(
        n_duplicate_rows=n_dup,
        duplicate_fraction=fraction(n_dup, len(frame)),
        n_duplicate_groups=n_groups,
        example_row_indices=[int(i) for i in examples],
        semantics=DUPLICATE_SEMANTICS,
    )


def redundancy(frame: pd.DataFrame, profiles: list[ColumnProfile]) -> RedundancySummary:
    usable = [p for p in profiles if not p.all_missing and not p.is_constant]

    buckets: dict[int, list[int]] = {}
    for p in usable:
        key = int(pd.util.hash_pandas_object(frame.iloc[:, p.position], index=False).sum())
        buckets.setdefault(key, []).append(p.position)
    groups: list[list[str]] = []
    for positions in buckets.values():
        while len(positions) > 1:
            first = frame.iloc[:, positions[0]]
            same = [q for q in positions[1:] if first.equals(frame.iloc[:, q])]
            if same:
                groups.append([profiles[q].name for q in [positions[0], *same]])
            positions = [q for q in positions[1:] if q not in same]  # groups follow column order
    duplicated_names = {name for g in groups for name in g[1:]}

    numeric = [
        p for p in usable if p.inferred_type is InferredType.numeric and p.name not in duplicated_names
    ]
    if len(numeric) > CORRELATION_MAX_COLUMNS:
        return RedundancySummary(
            duplicate_column_groups=groups,
            correlated_pairs=[],
            correlation_status="skipped",
            correlation_note=f"Correlation screening is limited to {CORRELATION_MAX_COLUMNS} "
            f"numeric columns; this dataset has {len(numeric)}.",
        )
    pairs: list[CorrelatedPair] = []
    if len(numeric) >= 2:
        block = frame.iloc[:, [p.position for p in numeric]].apply(
            lambda s: pd.to_numeric(s, errors="coerce").astype("float64")
        )
        block = block.replace([np.inf, -np.inf], np.nan)
        block.columns = range(len(numeric))
        corr = block.corr(method="pearson", min_periods=CORRELATION_MIN_PAIRS).to_numpy()
        notna = block.notna().to_numpy().astype(np.int64)
        counts = notna.T @ notna
        for i in range(len(numeric)):
            for j in range(i + 1, len(numeric)):
                r = corr[i, j]
                if np.isfinite(r) and abs(r) >= CORRELATION_THRESHOLD:
                    pairs.append(
                        CorrelatedPair(
                            column_a=numeric[i].name,
                            column_b=numeric[j].name,
                            pearson_r=round(float(r), 6),
                            n_pairs=int(counts[i, j]),
                        )
                    )
    return RedundancySummary(
        duplicate_column_groups=groups, correlated_pairs=pairs, correlation_status="computed"
    )
