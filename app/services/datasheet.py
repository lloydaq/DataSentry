"""Datasheet draft: dataset documentation pre-filled from the analysis, loosely following
"Datasheets for Datasets" (Gebru et al.).

Only what the analysis measured is filled in, and every filled field records where its value lives
in the analysis result (``source``, a JSON path), so the draft can be checked against it. What only
a person can know (why the data exists, how it was collected, consent, intended uses, maintenance)
is asked, never answered: those questions always come back empty.
"""

from datetime import UTC, datetime

from app.config import APP_VERSION
from app.models.schemas import (
    AnalysisResult,
    Datasheet,
    DatasheetField,
    DatasheetQuestion,
    DatasheetSection,
    FindingKind,
    TargetTask,
)

DISCLAIMER = (
    "This is a draft generated from the file's contents only. DataSentry does not know who created "
    "the dataset, why, or how it was collected; those sections are questions for a person to "
    "answer. Findings are prompts to investigate, not proof of a problem."
)
_PROBLEM_KINDS = (FindingKind.likely_issue, FindingKind.potential_issue, FindingKind.inconclusive)


def _pct(fraction: float) -> str:
    return f"{fraction:.1%}"


def _questions(*texts: str) -> list[DatasheetQuestion]:
    return [DatasheetQuestion(question=t) for t in texts]


def _composition(r: AnalysisResult) -> DatasheetSection:
    d, o = r.dataset, r.overview
    fields = [
        DatasheetField(label="File", value=d.filename, source="dataset.filename"),
        DatasheetField(label="SHA-256", value=d.sha256, source="dataset.sha256"),
        DatasheetField(label="Rows", value=str(d.n_rows), source="dataset.n_rows"),
        DatasheetField(label="Columns", value=str(d.n_columns), source="dataset.n_columns"),
        DatasheetField(label="Delimiter", value=d.parsing.delimiter, source="dataset.parsing.delimiter"),
        DatasheetField(label="Encoding", value=d.parsing.encoding, source="dataset.parsing.encoding"),
        DatasheetField(label="Missing cells", value=_pct(o.missing_cell_fraction),
                       source="overview.missing_cell_fraction"),
        DatasheetField(label="Rows with a missing value", value=_pct(o.rows_with_missing_fraction),
                       source="overview.rows_with_missing_fraction"),
    ]
    if d.parsing.missing_values:
        fields.append(DatasheetField(label="Extra missing-value tokens",
                                     value=", ".join(d.parsing.missing_values),
                                     source="dataset.parsing.missing_values"))
    if r.duplicates is not None:
        fields.append(DatasheetField(label="Exact duplicate rows", value=str(r.duplicates.n_duplicate_rows),
                                     source="duplicates.n_duplicate_rows"))
    for i, c in enumerate(r.columns or []):
        fields += [
            DatasheetField(label="Type", value=c.inferred_type.value, source=f"columns[{i}].inferred_type", group=c.name),
            DatasheetField(label="Missing", value=_pct(c.missing_fraction), source=f"columns[{i}].missing_fraction", group=c.name),
            DatasheetField(label="Distinct values", value=str(c.n_unique), source=f"columns[{i}].n_unique", group=c.name),
        ]
    return DatasheetSection(
        title="Composition",
        filled_by="both",
        fields=fields,
        questions=_questions(
            "What does each row represent (a person, an event, a transaction, a reading)?",
            "Is this the complete dataset or a sample? If a sample, how was it drawn?",
            "Does the data identify people directly or indirectly, or contain sensitive attributes?",
            "What do the columns mean, and in which units are they recorded?",
        ),
        note=None if r.columns is not None else "Column profiling did not complete, so per-column facts are missing.",
    )


def _target(r: AnalysisResult) -> DatasheetSection:
    questions = _questions(
        "How were the labels produced, and by whom?",
        "How was label quality checked, and how often are labels known to be wrong?",
    )
    t = r.target
    if t is None:
        return DatasheetSection(
            title="Target", filled_by="person",
            questions=_questions("Which column is the label, if any, and how was it produced?"),
            note="No target column was selected for this analysis.",
        )
    fields = [
        DatasheetField(label="Target column", value=t.column, source="target.column"),
        DatasheetField(label="Task", value=t.task.value, source="target.task"),
        DatasheetField(label="Labeled rows", value=str(t.n_labeled), source="target.n_labeled"),
        DatasheetField(label="Rows without a label", value=str(t.n_missing_labels), source="target.n_missing_labels"),
    ]
    if t.task is TargetTask.classification and t.classes is not None:
        fields.append(DatasheetField(label="Classes", value=str(t.classes.n_classes), source="target.classes.n_classes"))
        fields += [
            DatasheetField(label=f"Class {c.label}", value=f"{c.count} ({_pct(c.fraction)})",
                           source=f"target.classes.classes[{i}]")
            for i, c in enumerate(t.classes.classes)
        ]
        if t.classes.imbalance_ratio is not None:
            fields.append(DatasheetField(label="Largest to smallest class", value=f"{t.classes.imbalance_ratio:g}:1",
                                         source="target.classes.imbalance_ratio"))
    elif t.regression is not None:
        for key in ("min", "median", "mean", "max"):
            value = getattr(t.regression, key)
            if value is not None:
                fields.append(DatasheetField(label=key.capitalize(), value=f"{value:g}", source=f"target.regression.{key}"))
    return DatasheetSection(title="Target", filled_by="both", fields=fields, questions=questions)


def _known_issues(r: AnalysisResult) -> DatasheetSection:
    fields = [
        DatasheetField(label=f.title, value=f"{f.severity.value} · {f.kind.value.replace('_', ' ')}: {f.explanation}",
                       source=f"findings[{i}]")
        for i, f in enumerate(r.findings) if f.kind in _PROBLEM_KINDS
    ]
    fields += [
        DatasheetField(label="Not evaluated", value=text, source=f"summary.not_evaluated[{i}]")
        for i, text in enumerate(r.summary.not_evaluated)
    ]
    n_obs = sum(f.kind is FindingKind.observation for f in r.findings)
    return DatasheetSection(
        title="Known data-quality findings",
        filled_by="both",
        fields=fields,
        questions=_questions("Which of these findings are known and accepted, and why?"),
        note=(f"Likely and potential issues and inconclusive checks from the analysis; {n_obs} neutral "
              "observation(s) are in the full report. Findings are evidence to investigate, not proof."
              if fields else "The analysis reported no likely or potential issues."),
    )


def build_datasheet(result: AnalysisResult, generated_at: datetime | None = None) -> Datasheet:
    sections = [
        DatasheetSection(title="Motivation", filled_by="person", questions=_questions(
            "For what purpose was the dataset created? Which task or gap did it address?",
            "Who created the dataset, and on behalf of which person or organisation?",
            "Who funded its creation?",
        )),
        _composition(result),
        _target(result),
        _known_issues(result),
        DatasheetSection(title="Collection process", filled_by="person", questions=_questions(
            "How was the data collected (sensors, surveys, logs, manual entry, scraping)?",
            "Over what time period was it collected, and where?",
            "If people are described, were they informed, and did they consent? How?",
            "Was an ethical or legal review carried out?",
        )),
        DatasheetSection(
            title="Preprocessing, cleaning and labeling", filled_by="person",
            questions=_questions(
                "What was done to the data before this file (filtering, joins, imputation, deduplication)?",
                "Is the raw data kept, and where?",
            ),
            note="DataSentry did not modify this file; any corrections are applied to a separate copy.",
        ),
        DatasheetSection(title="Uses", filled_by="person", questions=_questions(
            "What is the dataset intended to be used for?",
            "What should it not be used for?",
            "Could its use harm or unfairly treat any group of people?",
        )),
        DatasheetSection(title="Distribution and maintenance", filled_by="person", questions=_questions(
            "Under which license or terms is the dataset shared?",
            "Who maintains it, and how are errors reported and corrected?",
            "Will it be updated, and how long will each version be kept?",
        )),
    ]
    return Datasheet(
        title=f"Datasheet draft: {result.dataset.filename}",
        generated_by=f"DataSentry {APP_VERSION}",
        generated_at=(generated_at or datetime.now(UTC)).isoformat(timespec="seconds"),
        source_filename=result.dataset.filename,
        source_sha256=result.dataset.sha256,
        sections=sections,
        disclaimer=DISCLAIMER,
    )


# --- Markdown -----------------------------------------------------------------------------------

# Dataset text never starts a line (it always follows a list marker, a label or a table pipe), so
# line-start markers such as "-", "+" and "1." cannot form lists and need no escaping.
_MD_SPECIAL = set("\\`*_{}[]()<>#|~")


def md(text: object) -> str:
    """Dataset text as inert Markdown: one line, every Markdown-significant character escaped,
    so a crafted value cannot add links, images, HTML or table cells."""
    flat = " ".join(str(text).split())
    return "".join(f"\\{ch}" if ch in _MD_SPECIAL else ch for ch in flat)


def render_markdown(sheet: Datasheet) -> str:
    """Section titles, notes, questions and the disclaimer are DataSentry's own text; everything
    that came from the dataset (file name, column names, labels, finding text) goes through md()."""
    lines = [
        f"# {md(sheet.title)}",
        "",
        f"> {sheet.disclaimer}",  # our own text, not dataset text
        "",
        f"Generated by {sheet.generated_by} on {sheet.generated_at} from {md(sheet.source_filename)} "
        f"(SHA-256 `{sheet.source_sha256}`).",
    ]
    for section in sheet.sections:
        who = {"analysis": "filled in from the analysis", "person": "to be completed by a person",
               "both": "partly filled in from the analysis; the questions are for a person"}[section.filled_by]
        lines += ["", f"## {section.title}", "", f"*{who}*"]
        if section.note:
            lines += ["", section.note]
        plain = [f for f in section.fields if f.group is None]
        grouped = [f for f in section.fields if f.group is not None]
        if plain:
            lines.append("")
            lines += [f"- **{md(f.label)}:** {md(f.value)}" for f in plain]
        if grouped:
            headers = list(dict.fromkeys(f.label for f in grouped))
            rows: dict[str, dict[str, str]] = {}
            for f in grouped:
                rows.setdefault(f.group, {})[f.label] = f.value
            lines += ["", "| Column | " + " | ".join(md(h) for h in headers) + " |",
                      "|---|" + "---|" * len(headers)]
            lines += [f"| {md(name)} | " + " | ".join(md(cells.get(h, "")) for h in headers) + " |"
                      for name, cells in rows.items()]
        for q in section.questions:
            lines += ["", f"**{q.question}**", "", "_To be completed by a person._"]
    return "\n".join(lines) + "\n"
