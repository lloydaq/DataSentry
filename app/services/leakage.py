"""Leakage screening.

These checks surface evidence worth investigating; none of them proves leakage. A feature that
predicts the target almost perfectly may be legitimate, and leakage can exist without any of these
signals (for example features computed after the prediction time).
"""

import numpy as np
import pandas as pd

from app.models.schemas import (
    Category,
    ColumnProfile,
    DatasetInfo,
    Finding,
    FindingKind,
    InferredType,
    LeakageSignal,
    Severity,
    TargetTask,
    TrainTestOverlapResult,
)
from app.services.loader import DatasetError, LoadedDataset
from app.services.profiler import fraction

LEAKAGE_MIN_LABELED = 20
MAPPING_MAX_UNIQUE_FRACTION = 0.5  # the feature must repeat values; unique IDs map trivially
MAPPING_MIN_GROUPED_FRACTION = 0.8  # share of rows that must sit in feature groups of 2+ rows
LAMBDA_THRESHOLD = 0.8
AUC_THRESHOLD = 0.99
CORRELATION_THRESHOLD = 0.99
OVERLAP_EXAMPLES_LIMIT = 10
_MISSING_TOKEN = "\x00missing"  # cannot occur in input: the loader rejects NUL bytes


def _auc(x: pd.Series, positive: pd.Series) -> float:
    ranks = x.rank(method="average")
    n1 = int(positive.sum())
    n0 = len(x) - n1
    return float((ranks[positive].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def _mapping_signal(feature: pd.Series, labels: pd.Series, column: str) -> LeakageSignal | None:
    """Goodman-Kruskal lambda: the share of majority-guess errors removed by knowing the feature."""
    present = feature.notna()
    feat, lab = feature[present], labels[present]
    n = len(feat)
    if n < LEAKAGE_MIN_LABELED or lab.nunique() < 2:
        return None
    sizes = feat.value_counts()
    if len(sizes) < 2 or len(sizes) > MAPPING_MAX_UNIQUE_FRACTION * n:
        return None
    if sizes[sizes >= 2].sum() < MAPPING_MIN_GROUPED_FRACTION * n:
        return None
    errors_without = n - int(lab.value_counts().iloc[0])
    per_group_majority = lab.groupby(feat.to_numpy()).agg(lambda g: g.value_counts().iloc[0])
    errors_with = n - int(per_group_majority.sum())
    lam = (errors_without - errors_with) / errors_without
    if lam < LAMBDA_THRESHOLD:
        return None
    return LeakageSignal(
        column=column,
        method="category_mapping",
        statistic=round(lam, 6),
        description=f"Knowing this feature's value removes {lam:.1%} of the errors made by always "
        f"guessing the majority class (Goodman-Kruskal lambda over {n} labeled rows and "
        f"{len(sizes)} distinct values).",
    )


def target_leakage_signals(
    frame: pd.DataFrame,
    profiles: list[ColumnProfile],
    target: str,
    task: TargetTask,
    labels: pd.Series,
) -> list[LeakageSignal]:
    """``labels`` holds the non-missing target values, indexed like ``frame``."""
    if len(labels) < LEAKAGE_MIN_LABELED:
        return []
    signals: list[LeakageSignal] = []
    binary = task is TargetTask.classification and labels.nunique() == 2
    positive = labels == sorted(labels.unique())[-1] if binary else None
    for p in profiles:
        if p.name == target or p.all_missing or p.is_constant:
            continue
        feature = frame.iloc[:, p.position].loc[labels.index]
        if task is TargetTask.classification:
            signal = _mapping_signal(feature, labels, p.name)
            if signal is None and binary and p.inferred_type is InferredType.numeric:
                x = pd.to_numeric(feature, errors="coerce").astype("float64")
                keep = np.isfinite(x)
                pos = positive[keep]
                if keep.sum() >= LEAKAGE_MIN_LABELED and 0 < pos.sum() < len(pos):
                    auc = _auc(x[keep], pos)
                    if max(auc, 1 - auc) >= AUC_THRESHOLD:
                        signal = LeakageSignal(
                            column=p.name,
                            method="single_feature_auc",
                            statistic=round(auc, 6),
                            description=f"This feature alone ranks the two classes with ROC AUC "
                            f"{auc:.4f} (1.0 or 0.0 means perfect separation).",
                        )
        elif p.inferred_type is InferredType.numeric:
            x = pd.to_numeric(feature, errors="coerce").astype("float64")
            pair = pd.DataFrame({"x": x, "y": labels}).replace([np.inf, -np.inf], np.nan).dropna()
            signal = None
            if len(pair) >= LEAKAGE_MIN_LABELED and pair["x"].std() > 0 and pair["y"].std() > 0:
                r = float(pair["x"].corr(pair["y"]))
                if np.isfinite(r) and abs(r) >= CORRELATION_THRESHOLD:
                    signal = LeakageSignal(
                        column=p.name,
                        method="pearson_correlation",
                        statistic=round(r, 6),
                        description=f"This feature has Pearson correlation {r:.4f} with the "
                        f"target across {len(pair)} rows.",
                    )
        else:
            signal = None
        if signal is not None:
            signals.append(signal)
    return signals


# --- Train/test overlap ----------------------------------------------------------------------


def _canonical(train: pd.Series, test: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Put a column from both files on a common representation so equal values hash equally."""
    numeric = all(
        pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s) for s in (train, test)
    )
    if numeric:
        return train.astype("float64"), test.astype("float64")
    return tuple(  # type: ignore[return-value]
        s.astype(object).where(s.notna(), _MISSING_TOKEN).astype(str) for s in (train, test)
    )


def _row_hashes(train: pd.DataFrame, test: pd.DataFrame, columns: list[str]) -> tuple[np.ndarray, np.ndarray]:
    pairs = [_canonical(train[c], test[c]) for c in columns]
    a = pd.concat([p[0] for p in pairs], axis=1, keys=range(len(columns)))
    b = pd.concat([p[1] for p in pairs], axis=1, keys=range(len(columns)))
    return (
        pd.util.hash_pandas_object(a, index=False).to_numpy(),
        pd.util.hash_pandas_object(b, index=False).to_numpy(),
    )


def _info(dataset: LoadedDataset) -> DatasetInfo:
    return DatasetInfo(
        filename=dataset.filename,
        size_bytes=dataset.size_bytes,
        sha256=dataset.sha256,
        n_rows=len(dataset.frame),
        n_columns=dataset.frame.shape[1],
    )


def train_test_overlap(
    train: LoadedDataset, test: LoadedDataset, target: str | None
) -> TrainTestOverlapResult:
    tr, te = train.frame, test.frame
    common = [c for c in tr.columns if c in te.columns]
    if not common:
        raise DatasetError("no_common_columns", "The two files share no column names.")
    if target is not None and target not in common:
        raise DatasetError(
            "unknown_target_column", "The selected target column is not present in both files."
        )
    train_only = [c for c in tr.columns if c not in te.columns]
    test_only = [c for c in te.columns if c not in tr.columns]

    h_train, h_test = _row_hashes(tr, te, common)
    exact = np.isin(h_test, h_train)
    n_exact = int(exact.sum())

    n_feature_matches = n_label_conflicts = None
    features = [c for c in common if c != target]
    if target is not None and features:
        f_train, f_test = _row_hashes(tr, te, features)
        feature_match = np.isin(f_test, f_train)
        n_feature_matches = int(feature_match.sum())
        # A feature match that is not also an exact match must carry a label unseen for those features.
        n_label_conflicts = int((feature_match & ~exact).sum())

    findings: list[Finding] = []
    if n_exact:
        findings.append(
            Finding(
                code="train_test_row_overlap",
                kind=FindingKind.likely_issue,
                severity=Severity.high,
                category=Category.leakage,
                title="Test rows also appear in the training data",
                explanation=f"{n_exact} of {len(te)} test rows ({fraction(n_exact, len(te)):.1%}) "
                f"exactly match a training row on all {len(common)} shared columns.",
                why_it_matters="A model evaluated on rows it was trained on reports optimistic "
                "metrics that will not hold on genuinely unseen data.",
                recommendation="Remove the overlapping rows from the test set, or re-split the data "
                "after deduplication (grouping related records if they share an entity).",
                limitations="Rows are compared with 64-bit hashes of parsed values; collisions are "
                "possible but extremely unlikely. Near-duplicates are not detected.",
                columns=[],
                evidence={
                    "n_test_rows_in_train": n_exact,
                    "n_test_rows": len(te),
                    "n_columns_compared": len(common),
                },
            )
        )
    if n_label_conflicts:
        findings.append(
            Finding(
                code="train_test_label_conflict",
                kind=FindingKind.potential_issue,
                severity=Severity.medium,
                category=Category.leakage,
                title="Test rows match training features but carry a different label",
                explanation=f"{n_label_conflicts} test rows have feature values identical to at "
                "least one training row but a target value not seen with those features.",
                why_it_matters="Identical inputs with different labels point to label noise, "
                "missing features, or records that should be grouped during splitting.",
                recommendation="Inspect these records to decide whether the labels are wrong or "
                "whether additional features distinguish them.",
                columns=[target] if target else [],
                evidence={"n_rows": n_label_conflicts},
            )
        )
    if train_only or test_only:
        findings.append(
            Finding(
                code="train_test_schema_mismatch",
                kind=FindingKind.potential_issue,
                severity=Severity.low,
                category=Category.consistency,
                title="The two files have different columns",
                explanation=f"{len(train_only)} column(s) exist only in the training file and "
                f"{len(test_only)} only in the test file. Only shared columns were compared.",
                why_it_matters="A model trained on columns missing at evaluation time cannot be "
                "applied as-is, and overlap checks ignore the unshared columns.",
                recommendation="Confirm that both files come from the same pipeline and schema.",
                columns=train_only + test_only,
                evidence={"n_train_only": len(train_only), "n_test_only": len(test_only)},
            )
        )

    return TrainTestOverlapResult(
        train=_info(train),
        test=_info(test),
        target_column=target,
        common_columns=common,
        train_only_columns=train_only,
        test_only_columns=test_only,
        n_test_rows_in_train=n_exact,
        test_rows_in_train_fraction=fraction(n_exact, len(te)),
        n_test_feature_matches=n_feature_matches,
        n_feature_matches_with_different_label=n_label_conflicts,
        example_test_row_indices=[int(i) for i in np.flatnonzero(exact)[:OVERLAP_EXAMPLES_LIMIT]],
        findings=findings,
        limitations=[
            "Exact matching only: rounding differences, reformatted text or near-duplicates are "
            "not detected.",
            "Columns are compared by name; a column parsed as numbers in one file and as text in "
            "the other is compared as text and may not match.",
            "Related-but-different records (for example the same customer at two dates) are not "
            "detected; use group-aware splitting when entities repeat.",
        ],
    )
