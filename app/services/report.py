"""JSON and self-contained HTML reports.

By default reports omit example cell values (frequent categories and spelling variants), so a
report can be shared without copying raw data; class labels of the selected target are kept
because target checks are meaningless without them. Every dynamic string in the HTML report is
escaped, and the page declares a Content-Security-Policy that forbids scripts.
"""

from datetime import UTC, datetime
from html import escape

from app.config import APP_VERSION
from app.models.schemas import AnalysisResult, ColumnProfile, Finding, ReportDocument, ReportMetadata
from app.services import findings as F
from app.services import leakage as L
from app.services import profiler as P
from app.services import target as T

SERIALIZATION_POLICY = (
    "Strict JSON: NaN and infinity are never emitted. Statistics that are undefined (for example "
    "the standard deviation of one value, or the mean of an all-missing column) are null, and "
    "infinite inputs are counted separately and excluded from statistics. Floats are rounded to "
    "6 decimal places."
)
PRIVACY_NOTE = (
    "The uploaded file is processed in memory and not stored. This report does not contain the "
    "dataset's rows. Column names, statistics and target class labels are included"
)

METHODOLOGY = [
    f"Types: numeric and boolean types come from the CSV parser; text columns whose values are all "
    f"'true'/'false' are boolean, all ISO 8601 dates are datetime, at most "
    f"{P.CATEGORICAL_MAX_UNIQUE} distinct values (or a distinct ratio of at most "
    f"{P.CATEGORICAL_MAX_UNIQUE_FRACTION}) is categorical, otherwise text.",
    f"Missing values: columns missing at least {F.MISSING_REPORT_FRACTION:.0%} of values are "
    f"reported individually (medium severity from {F.MISSING_HIGH_FRACTION:.0%}); smaller amounts "
    "are summarized as one observation.",
    f"Duplicates: {P.DUPLICATE_SEMANTICS} Medium severity from {F.DUPLICATE_MEDIUM_FRACTION:.0%} "
    "of rows.",
    f"Near-constant: the most frequent value covers at least {F.NEAR_CONSTANT_FRACTION:.0%} of "
    f"non-missing values in a column with at least {F.NEAR_CONSTANT_MIN_ROWS} of them.",
    f"Identifier-like: every one of at least {P.IDENTIFIER_MIN_ROWS} rows has a distinct, "
    "non-missing integer or string value. High cardinality: categorical or text columns with at "
    f"least {F.HIGH_CARDINALITY_MIN_UNIQUE} distinct values covering at least "
    f"{F.HIGH_CARDINALITY_FRACTION:.0%} of non-missing values.",
    f"Redundancy: identical columns are compared exactly; numeric pairs with |Pearson r| >= "
    f"{P.CORRELATION_THRESHOLD} over at least {P.CORRELATION_MIN_PAIRS} rows are reported "
    f"(screening limited to {P.CORRELATION_MAX_COLUMNS} numeric columns).",
    "Outlier candidates: Tukey fences at Q1 - 1.5 x IQR and Q3 + 1.5 x IQR, computed when a column "
    f"has at least {P.OUTLIER_MIN_VALUES} finite values and a non-zero IQR.",
    f"Rare categories: below {P.RARE_CATEGORY_FRACTION:.0%} of non-missing values, evaluated when a "
    f"column has at least {P.RARE_CATEGORY_MIN_ROWS} values and at most "
    f"{P.RARE_CATEGORY_MAX_UNIQUE} categories. Variants: values equal after trimming, collapsing "
    "whitespace and ignoring case.",
    f"Mixed types: at least {F.MIXED_TYPE_NUMERIC_FRACTION:.0%} but not all values of a text "
    "column parse as numbers.",
    "Target task: boolean and non-numeric targets are classification; integer-valued numeric "
    f"targets with at most {T.INTEGER_CLASS_MAX_UNIQUE} distinct values are classification; "
    f"other numeric targets are regression. Rare classes have fewer than "
    f"{T.RARE_CLASS_THRESHOLD} examples. Imbalance (largest/smallest class) is an observation "
    f"from {F.IMBALANCE_OBSERVATION_RATIO:.0f}:1 and never a defect by itself.",
    "Leakage screen (needs a target and at least "
    f"{L.LEAKAGE_MIN_LABELED} labeled rows): a repeated-value feature whose Goodman-Kruskal "
    f"lambda with a class target is at least {L.LAMBDA_THRESHOLD} (it removes that share of "
    "majority-guess errors); a numeric feature with single-feature ROC AUC >= {L.AUC_THRESHOLD} (binary targets); "
    f"or |Pearson r| >= {L.CORRELATION_THRESHOLD} with a regression target. These are prompts to "
    "investigate, not proof.",
    "Summary: no numeric score. A category is 'issue' if it has a likely or potential problem of "
    "high or medium severity, 'review' for lower-severity problems or inconclusive checks, "
    "'pass' when only observations remain, and 'not_evaluated' when its checks did not run.",
]


def build_report(
    result: AnalysisResult, include_values: bool, generated_at: datetime | None = None
) -> ReportDocument:
    analysis = result if include_values else redact_values(result)
    note = PRIVACY_NOTE + (
        ", together with frequent category values."
        if include_values
        else "; frequent category values and spelling variants are omitted."
    )
    return ReportDocument(
        metadata=ReportMetadata(
            tool_version=APP_VERSION,
            generated_at=(generated_at or datetime.now(UTC)).isoformat(timespec="seconds"),
            include_value_examples=include_values,
            serialization_policy=SERIALIZATION_POLICY,
            privacy_note=note,
        ),
        analysis=analysis,
        methodology=METHODOLOGY,
    )


def redact_values(result: AnalysisResult) -> AnalysisResult:
    redacted = result.model_copy(deep=True)
    for column in redacted.columns or []:
        if column.categorical is not None:
            column.categorical.top_values = []
            column.categorical.variant_groups = []
            column.categorical.values_redacted = True
    return redacted


# --- HTML ------------------------------------------------------------------------------------

_CSS = """
:root{--fg:#1d2433;--muted:#5b6475;--line:#dde2ea;--bg:#ffffff;--soft:#f5f7fa;--accent:#2f5bd3;
--high:#b42318;--medium:#b54708;--low:#175cd3;--info:#475467}
*{box-sizing:border-box}body{margin:0;font:14px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
color:var(--fg);background:var(--bg)}main{max-width:1040px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:36px 0 12px;padding-bottom:6px;
border-bottom:1px solid var(--line)}h3{font-size:15px;margin:0 0 6px}
.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.card{border:1px solid var(--line);border-radius:8px;padding:12px 14px;background:var(--soft)}
.card b{display:block;font-size:20px}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--soft);font-weight:600}td.num{text-align:right;font-variant-numeric:tabular-nums}
.finding{border:1px solid var(--line);border-left:4px solid var(--info);border-radius:6px;
padding:12px 14px;margin:0 0 10px}.finding.high{border-left-color:var(--high)}
.finding.medium{border-left-color:var(--medium)}.finding.low{border-left-color:var(--low)}
.tag{display:inline-block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.03em;
padding:1px 7px;border-radius:999px;border:1px solid var(--line);margin-right:4px;color:var(--muted)}
.tag.high{color:var(--high)}.tag.medium{color:var(--medium)}.tag.low{color:var(--low)}
dl{display:grid;grid-template-columns:140px 1fr;gap:2px 12px;margin:8px 0 0}dt{color:var(--muted)}dd{margin:0}
code{font-family:ui-monospace,Consolas,monospace;font-size:12px}
.status{font-size:16px;font-weight:600}ul{padding-left:20px}
@media print{main{padding:0}.finding{break-inside:avoid}}
"""


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _num(value: float | int | None, pct: bool = False) -> str:
    if value is None:
        return "—"
    if pct:
        return f"{value:.1%}"
    if isinstance(value, float):
        return f"{value:,.4g}"
    return f"{value:,}"


def _finding_html(f: Finding) -> str:
    evidence = "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in f.evidence.items())
    columns = ", ".join(f"<code>{_e(c)}</code>" for c in f.columns) or "Whole dataset"
    limitation = f"<dt>Limitations</dt><dd>{_e(f.limitations)}</dd>" if f.limitations else ""
    return (
        f'<div class="finding {_e(f.severity.value)}">'
        f'<span class="tag {_e(f.severity.value)}">{_e(f.severity.value)}</span>'
        f'<span class="tag">{_e(f.kind.value.replace("_", " "))}</span>'
        f'<span class="tag">{_e(f.category.value.replace("_", " "))}</span>'
        f"<h3>{_e(f.title)}</h3><p>{_e(f.explanation)}</p><dl>"
        f"<dt>Affected</dt><dd>{columns}</dd>"
        f"<dt>Why it matters</dt><dd>{_e(f.why_it_matters)}</dd>"
        f"<dt>Next step</dt><dd>{_e(f.recommendation)}</dd>{limitation}"
        f"<dt>Code</dt><dd><code>{_e(f.code)}</code></dd>{evidence}</dl></div>"
    )


def _column_row(c: ColumnProfile) -> str:
    detail = ""
    if c.numeric:
        n = c.numeric
        detail = (
            f"min {_num(n.min)} · median {_num(n.median)} · max {_num(n.max)} · "
            f"mean {_num(n.mean)} · sd {_num(n.std)}"
        )
        if n.outliers.status == "computed":
            detail += f" · {n.outliers.n_below + n.outliers.n_above} outside IQR fences"
    elif c.categorical:
        s = c.categorical
        if s.values_redacted:
            detail = f"{s.n_unique} categories (values omitted)"
        else:
            detail = "top: " + ", ".join(f"{v.value} ({v.count})" for v in s.top_values[:5])
    elif c.datetime:
        detail = f"{c.datetime.min} → {c.datetime.max}"
    flags = [
        label
        for flag, label in (
            (c.all_missing, "all missing"),
            (c.is_constant, "constant"),
            (c.identifier_like, "identifier-like"),
        )
        if flag
    ]
    return (
        f"<tr><td><code>{_e(c.name)}</code></td><td>{_e(c.inferred_type.value)}</td>"
        f'<td class="num">{_num(c.missing_fraction, pct=True)}</td>'
        f'<td class="num">{_num(c.n_unique)}</td><td>{_e(", ".join(flags))}</td>'
        f"<td>{_e(detail)}</td></tr>"
    )


def render_html(doc: ReportDocument) -> str:
    a = doc.analysis
    s = a.summary
    o = a.overview
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<meta http-equiv='Content-Security-Policy' "
        "content=\"default-src 'none'; style-src 'unsafe-inline'\">",
        f"<title>DataSentry report: {_e(a.dataset.filename)}</title><style>{_CSS}</style></head>",
        "<body><main>",
        f"<h1>DataSentry report</h1><p class='muted'><code>{_e(a.dataset.filename)}</code> · "
        f"SHA-256 <code>{_e(a.dataset.sha256[:16])}…</code> · generated "
        f"{_e(doc.metadata.generated_at)} · DataSentry {_e(doc.metadata.tool_version)}</p>",
        "<h2>Executive summary</h2>",
        f"<p class='status'>{_e(s.headline)}</p>",
        f"<p>Analysis status: <b>{_e(a.status)}</b>. Overall: <b>{_e(s.status.replace('_', ' '))}</b>."
        f" Target column: <b>{_e(a.settings.target_column or 'none selected')}</b>.</p>",
        "<table><tr><th>Category</th><th>Status</th><th class='num'>Findings</th></tr>",
        *(
            f"<tr><td>{_e(c.category.value.replace('_', ' '))}</td><td>{_e(c.status.replace('_', ' '))}"
            f"</td><td class='num'>{c.n_findings}</td></tr>"
            for c in s.categories
        ),
        "</table>",
    ]
    if s.not_evaluated:
        parts.append("<p class='muted'>Not evaluated:</p><ul>")
        parts += [f"<li>{_e(n)}</li>" for n in s.not_evaluated]
        parts.append("</ul>")
    parts.append(f"<p class='muted'>{_e(s.score_policy)}</p>")

    parts += [
        "<h2>Dataset overview</h2><div class='grid'>",
        f"<div class='card'><span class='muted'>Rows</span><b>{_num(o.n_rows)}</b></div>",
        f"<div class='card'><span class='muted'>Columns</span><b>{_num(o.n_columns)}</b></div>",
        f"<div class='card'><span class='muted'>Missing cells</span><b>"
        f"{_num(o.missing_cell_fraction, pct=True)}</b></div>",
        f"<div class='card'><span class='muted'>Rows with missing</span><b>"
        f"{_num(o.n_rows_with_missing)}</b></div>",
    ]
    if a.duplicates:
        parts.append(
            f"<div class='card'><span class='muted'>Duplicate rows</span><b>"
            f"{_num(a.duplicates.n_duplicate_rows)}</b></div>"
        )
    parts.append(
        f"<div class='card'><span class='muted'>Memory (approx.)</span><b>"
        f"{_num(round(o.memory_bytes / 1024))} KiB</b></div></div>"
    )

    parts.append(f"<h2>Findings ({len(a.findings)})</h2>")
    parts += [_finding_html(f) for f in a.findings] or ["<p>No findings.</p>"]

    if a.target:
        t = a.target
        parts.append(
            f"<h2>Target analysis</h2><p><code>{_e(t.column)}</code> treated as "
            f"<b>{_e(t.task.value)}</b>. {_e(t.task_reason)}</p>"
        )
        if t.classes:
            parts.append(
                "<table><tr><th>Class</th><th class='num'>Count</th><th class='num'>Share</th></tr>"
            )
            parts += [
                f"<tr><td>{_e(c.label)}</td><td class='num'>{c.count:,}</td>"
                f"<td class='num'>{c.fraction:.1%}</td></tr>"
                for c in t.classes.classes
            ]
            parts.append("</table>")
            if t.classes.truncated:
                parts.append(f"<p class='muted'>Showing the {len(t.classes.classes)} largest of "
                             f"{t.classes.n_classes} classes.</p>")

    if a.columns:
        parts.append(
            "<h2>Column diagnostics</h2><table><tr><th>Column</th><th>Type</th>"
            "<th class='num'>Missing</th><th class='num'>Distinct</th><th>Flags</th>"
            "<th>Summary</th></tr>"
        )
        parts += [_column_row(c) for c in a.columns]
        parts.append("</table>")

    if a.corrections:
        parts.append("<h2>Suggested corrections</h2><p class='muted'>None of these were applied. "
                     "Each requires explicit approval in DataSentry.</p><ul>")
        parts += [
            f"<li><b>{_e(c.title)}</b>: {_e(c.description)} <span class='muted'>"
            f"{_e(c.implications)}</span></li>"
            for c in a.corrections
        ]
        parts.append("</ul>")

    parts.append("<h2>Methodology</h2><ul>")
    parts += [f"<li>{_e(m)}</li>" for m in doc.methodology]
    parts.append("</ul><h2>Limitations</h2><ul>")
    parts += [f"<li>{_e(x)}</li>" for x in a.limitations]
    parts.append(f"<li>{_e(doc.metadata.privacy_note)}</li></ul>")
    parts.append("<h2>Analysis stages</h2><ul>")
    parts += [f"<li>{_e(st.name)}: {_e(st.status)}</li>" for st in a.stages]
    parts.append("</ul></main></body></html>")
    return "".join(parts)
