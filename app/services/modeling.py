"""The shared baseline model for opt-in ML checks (label review and model-impact experiments).

One simple, deterministic model: median-imputed, standardized numeric features and one-hot
categorical features into a logistic regression. Preprocessing lives inside the pipeline, so it is
fitted on training data only wherever the pipeline is fitted.
"""

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.models.schemas import ColumnProfile, ExcludedFeature, InferredType

MAX_CATEGORIES = 50  # categorical features with more distinct values are excluded
MAX_FEATURES = 200
MODEL_DESCRIPTION = (
    "LogisticRegression(max_iter=1000) on median-imputed, standardized numeric features and "
    "one-hot encoded categorical features"
)
_MISSING_CATEGORY = "__missing__"


def select_features(
    profiles: list[ColumnProfile], target_column: str, leaky: set[str]
) -> tuple[list[str], list[str], list[ExcludedFeature]]:
    """Usable numeric and categorical feature columns, and why every other column is excluded.
    Columns flagged by the leakage screen are excluded with that reason."""
    numeric: list[str] = []
    categorical: list[str] = []
    excluded: list[ExcludedFeature] = []
    for p in profiles:
        if p.name == target_column:
            continue
        reason = None
        if p.all_missing or p.is_constant:
            reason = "no variation"
        elif p.identifier_like:
            reason = "identifier-like"
        elif p.name in leaky:
            reason = "possible target leakage"
        elif p.inferred_type is InferredType.numeric:
            numeric.append(p.name)
        elif p.inferred_type in (InferredType.categorical, InferredType.boolean):
            if p.n_unique <= MAX_CATEGORIES:
                categorical.append(p.name)
            else:
                reason = f"more than {MAX_CATEGORIES} categories"
        else:
            reason = f"{p.inferred_type.value} columns are not used"
        if reason:
            excluded.append(ExcludedFeature(column=p.name, reason=reason))
    return numeric, categorical, excluded


def usable_kind(profile: ColumnProfile) -> str | None:
    """'numeric' or 'categorical' when the column could be a feature apart from leakage."""
    if profile.all_missing or profile.is_constant or profile.identifier_like:
        return None
    if profile.inferred_type is InferredType.numeric:
        return "numeric"
    if profile.inferred_type in (InferredType.categorical, InferredType.boolean) and (
        profile.n_unique <= MAX_CATEGORIES
    ):
        return "categorical"
    return None


def feature_matrix(
    frame: pd.DataFrame, rows: pd.Index, numeric: list[str], categorical: list[str]
) -> pd.DataFrame:
    X = pd.DataFrame(index=rows)
    for c in numeric:
        X[c] = pd.to_numeric(frame.loc[rows, c], errors="coerce").astype("float64").replace(
            [np.inf, -np.inf], np.nan
        )
    for c in categorical:
        col = frame.loc[rows, c]
        X[c] = col.astype(str).where(col.notna(), _MISSING_CATEGORY).astype(object)
    return X


def build_model(numeric: list[str], categorical: list[str]) -> Pipeline:
    transformers = []
    if numeric:
        transformers.append(
            (
                "num",
                Pipeline(
                    [("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
                     ("scale", StandardScaler())]
                ),
                numeric,
            )
        )
    if categorical:
        transformers.append(("cat", OneHotEncoder(handle_unknown="ignore"), categorical))
    return Pipeline(
        [
            ("prep", ColumnTransformer(transformers)),
            ("clf", LogisticRegression(max_iter=1000)),
        ]
    )
