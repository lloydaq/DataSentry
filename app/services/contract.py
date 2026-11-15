"""Data contracts: turn one good dataset into checks for the next one.

``export_contract`` infers a contract from a dataset: column types, nullability, numeric ranges,
allowed categories and uniqueness, all taken from what was observed. An inferred contract is a
starting point to review and edit, not a statement of truth. ``check_contract`` validates a file
against a contract; every violation is reported with row counts and row numbers, never cell values.

Contracts arrive from users, so they are parsed as untrusted JSON: size-capped, validated by a
strict model (unknown keys rejected) and checked for consistency before use.
"""

import pandas as pd
from pydantic import ValidationError

from app.config import APP_VERSION, Limits
from app.models.schemas import (
    Category,
    ColumnProfile,
    ContractCheckResult,
    ContractColumn,
    ContractSource,
    ContractViolation,
    DataContract,
    Finding,
    FindingKind,
    InferredType,
    Severity,
)
from app.services.loader import DatasetError, LoadedDataset, ParseOptions, describe
from app.services.profiler import label_strings, parse_iso_times, profile_columns

CONTRACT_MAX_BYTES = 1_000_000  # a contract file larger than this is rejected
EXPORT_MAX_ALLOWED_VALUES = 100  # exported contracts list categories only up to this many
CHECK_MAX_ALLOWED_VALUES = 1000  # a contract may list at most this many values per column
VALUE_MAX_LENGTH = 200  # longest allowed value, in characters
VIOLATION_EXAMPLES_LIMIT = 10

_CATEGORY_TYPES = ("categorical", "boolean")
_BOOLEAN_TOKENS = frozenset({"true", "false"})

LIMITATIONS = [
    "An exported contract describes the file it came from: ranges are the observed minimum and "
    "maximum, and categories are the values that occurred. Widen or remove rules that should allow "
    "more.",
    "Types are checked per value: numeric means finite numbers, boolean means true/false, datetime "
    "means ISO 8601. Categorical and text accept any value.",
    "Row numbers count data rows from 1, excluding the header and skipped blank lines.",
]

_RULE_TEXT = {
    "missing_column": ("A required column is missing", Severity.high, Category.consistency),
    "unexpected_column": ("The file has a column the contract does not allow", Severity.medium,
                          Category.consistency),
    "type": ("Values do not match the contract type", Severity.high, Category.consistency),
    "not_nullable": ("Missing values in a column the contract marks as required",
                     Severity.medium, Category.completeness),
    "unique": ("Repeated values in a column the contract marks as unique", Severity.medium,
               Category.uniqueness),
    "min": ("Values below the contract minimum", Severity.medium, Category.distribution),
    "max": ("Values above the contract maximum", Severity.medium, Category.distribution),
    "allowed_values": ("Values outside the contract's allowed list", Severity.medium,
                       Category.consistency),
}


# --- Export -------------------------------------------------------------------------------------


def _contract_column(series: pd.Series, profile: ColumnProfile) -> ContractColumn:
    kind = profile.inferred_type
    column = ContractColumn(
        name=profile.name,
        type="text" if kind is InferredType.empty else kind.value,
        nullable=profile.n_missing > 0,
        unique=profile.identifier_like,
    )
    if kind is InferredType.numeric and profile.numeric is not None:
        column.min, column.max = profile.numeric.min, profile.numeric.max
    elif kind.value in _CATEGORY_TYPES:
        values = sorted(set(label_strings(series)))
        if len(values) <= EXPORT_MAX_ALLOWED_VALUES and all(len(v) <= VALUE_MAX_LENGTH for v in values):
            column.allowed_values = values
    return column


def export_contract(dataset: LoadedDataset, target_column: str | None) -> DataContract:
    frame = dataset.frame
    if target_column is not None and target_column not in frame.columns:
        raise DatasetError(
            "unknown_target_column", "The selected target column does not exist in the dataset."
        )
    profiles = profile_columns(frame)
    return DataContract(
        contract_version="1",
        generated_by=f"DataSentry {APP_VERSION}",
        source=ContractSource(filename=dataset.filename, sha256=dataset.sha256, n_rows=len(frame)),
        parsing=dataset.options.info(),
        target_column=target_column,
        allow_extra_columns=True,
        columns=[_contract_column(frame[p.name], p) for p in profiles],
    )


# --- Parsing an uploaded contract ---------------------------------------------------------------


def _invalid(detail: str) -> DatasetError:
    return DatasetError("invalid_contract", f"The contract is not valid: {detail}")


def parse_contract(raw: bytes, limits: Limits) -> DataContract:
    if len(raw) > CONTRACT_MAX_BYTES:
        raise _invalid(f"the file is larger than {CONTRACT_MAX_BYTES} bytes.")
    try:
        contract = DataContract.model_validate_json(raw)
    except ValidationError:
        raise _invalid("it must be a DataSentry contract (JSON, contract_version \"1\").") from None
    if len(contract.columns) > limits.max_columns:
        raise _invalid(f"it lists more than {limits.max_columns} columns.")
    names = [c.name for c in contract.columns]
    if any(not n.strip() for n in names):
        raise _invalid("every column needs a non-empty name.")
    if len(set(names)) != len(names):
        raise _invalid("column names must be unique.")
    if contract.target_column is not None and contract.target_column not in names:
        raise _invalid("the target column must be one of the listed columns.")
    for c in contract.columns:
        if (c.min is not None or c.max is not None) and c.type != "numeric":
            raise _invalid("min and max apply to numeric columns only.")
        if c.min is not None and c.max is not None and c.min > c.max:
            raise _invalid("a column's min is larger than its max.")
        if c.allowed_values is not None:
            if c.type not in _CATEGORY_TYPES:
                raise _invalid("allowed_values apply to categorical and boolean columns only.")
            if len(c.allowed_values) > CHECK_MAX_ALLOWED_VALUES:
                raise _invalid(f"a column lists more than {CHECK_MAX_ALLOWED_VALUES} allowed values.")
            if any(len(v) > VALUE_MAX_LENGTH for v in c.allowed_values):
                raise _invalid(f"allowed values are limited to {VALUE_MAX_LENGTH} characters.")
    return contract


def contract_options(contract: DataContract) -> ParseOptions:
    """The parsing options a contract was exported with; the checked file is read the same way."""
    p = contract.parsing
    return ParseOptions(delimiter=p.delimiter, encoding=p.encoding, missing_values=tuple(p.missing_values))


# --- Check --------------------------------------------------------------------------------------


def _type_failures(series: pd.Series, kind: str) -> pd.Series:
    present = series.notna()
    if kind == "numeric":
        numbers = pd.to_numeric(series, errors="coerce").astype("float64")
        return present & ~numbers.abs().lt(float("inf"))  # NaN (unparsed) and infinity both fail
    if kind == "boolean":
        if pd.api.types.is_bool_dtype(series):
            return pd.Series(False, index=series.index)
        tokens = series.astype(str).str.strip().str.lower()
        return present & ~tokens.isin(_BOOLEAN_TOKENS)
    if kind == "datetime":
        parsed = parse_iso_times(series).reindex(series.index)
        return present & parsed.isna()
    return pd.Series(False, index=series.index)


def _violation(rule: str, column: str, mask: pd.Series | None, message: str) -> ContractViolation:
    if mask is None:
        n, rows = 0, []
    else:
        positions = [i for i, bad in enumerate(mask.to_numpy()) if bad]
        n, rows = len(positions), [p + 1 for p in positions[:VIOLATION_EXAMPLES_LIMIT]]
    return ContractViolation(rule=rule, column=column, n_rows=n, example_rows=rows, message=message)


def _column_violations(series: pd.Series, rule: ContractColumn) -> tuple[list[ContractViolation], int]:
    found: list[ContractViolation] = []
    checks = 1
    bad_type = _type_failures(series, rule.type)
    if bad_type.any():
        found.append(_violation("type", rule.name, bad_type,
                                f"{int(bad_type.sum())} value(s) are not {rule.type}."))
    if not rule.nullable:
        checks += 1
        missing = series.isna()
        if missing.any():
            found.append(_violation("not_nullable", rule.name, missing,
                                    f"{int(missing.sum())} row(s) are missing a value."))
    if rule.unique:
        checks += 1
        repeated = series.notna() & series.duplicated(keep=False)
        if repeated.any():
            found.append(_violation("unique", rule.name, repeated,
                                    f"{int(repeated.sum())} row(s) share a value with another row."))
    if rule.min is not None or rule.max is not None:
        numbers = pd.to_numeric(series, errors="coerce").astype("float64")
        for bound, op, name in ((rule.min, numbers.lt, "min"), (rule.max, numbers.gt, "max")):
            if bound is None:
                continue
            checks += 1
            outside = op(bound)
            if outside.any():
                word = "below the minimum" if name == "min" else "above the maximum"
                found.append(_violation(name, rule.name, outside,
                                        f"{int(outside.sum())} value(s) are {word} of {bound:g}."))
    if rule.allowed_values is not None:
        checks += 1
        allowed = set(rule.allowed_values)
        text = label_strings(series).reindex(series.index)
        outside = series.notna() & ~text.isin(allowed)
        if outside.any():
            found.append(_violation("allowed_values", rule.name, outside,
                                    f"{int(outside.sum())} value(s) are not in the allowed list."))
    return found, checks


def _finding(v: ContractViolation) -> Finding:
    title, severity, category = _RULE_TEXT[v.rule]
    rows = ", ".join(str(r) for r in v.example_rows)
    return Finding(
        code=f"contract_{v.rule}",
        kind=FindingKind.likely_issue,
        severity=severity,
        category=category,
        title=title,
        explanation=f"Column '{v.column}': {v.message}" + (f" First rows: {rows}." if rows else ""),
        why_it_matters="The file does not meet the expectations recorded in the contract, so code "
        "and models built on those expectations may fail or behave differently.",
        recommendation="Fix the data upstream, or update the contract if the new values are valid.",
        columns=[v.column],
        evidence={"rule": v.rule, "n_rows": v.n_rows, "first_rows": rows or None},
    )


def check_contract(dataset: LoadedDataset, contract: DataContract) -> ContractCheckResult:
    frame = dataset.frame
    violations: list[ContractViolation] = []
    n_rules = 0
    listed = {c.name for c in contract.columns}
    for rule in contract.columns:
        n_rules += 1  # presence
        if rule.name not in frame.columns:
            if rule.required:
                violations.append(_violation("missing_column", rule.name, None,
                                             "The column is required but not in the file."))
            continue
        found, checks = _column_violations(frame[rule.name], rule)
        violations += found
        n_rules += checks
    if not contract.allow_extra_columns:
        n_rules += 1
        violations += [
            _violation("unexpected_column", c, None, "The contract does not allow extra columns.")
            for c in frame.columns if c not in listed
        ]
    return ContractCheckResult(
        dataset=describe(dataset),
        passed=not violations,
        n_columns_checked=sum(c.name in frame.columns for c in contract.columns),
        n_rules_checked=n_rules,
        violations=violations,
        findings=[_finding(v) for v in violations],
        limitations=LIMITATIONS,
    )
