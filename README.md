# DataSentry

DataSentry is a local-first dataset diagnostics tool for machine-learning practitioners. Upload a
CSV file and it profiles the data, explains potential quality problems with the evidence behind
each one, checks a chosen target column for class balance, label conflicts and leakage signals, and
produces JSON and HTML reports. Optional checks review labels with cross-validated predictions and
compare a training file against a test file. Corrections are only applied after explicit approval,
to a copy, with an audit record.

Everything runs locally: no external API, LLM, database, account or cloud service is needed.

DataSentry separates **observations** (facts, such as class imbalance or outliers) from
**potential problems** (patterns that often hurt modeling) and **likely problems** (facts that
almost always do, such as an all-missing column). It does not produce a single "quality score";
see [Why there is no score](#why-there-is-no-score).

## Features

All of the following are implemented and covered by tests:

| Area | What DataSentry reports |
|---|---|
| Overview | Rows, columns, inferred column types, approximate memory, missing cells, rows with missing values |
| Missing values | Per-column counts and percentages, all-missing columns, rows with any missing value |
| Duplicates | Exact duplicate rows (count, percentage, repeated records, example row positions) |
| Column quality | Constant and near-constant columns, identifier-like columns, high cardinality, identical columns, near-perfectly correlated numeric pairs |
| Consistency | Numbers stored as text, category values that differ only by case or spacing, leading/trailing whitespace, infinite values |
| Numeric statistics | Min, max, mean, median, standard deviation, 5th/25th/75th/95th percentiles, zeros, negatives, IQR outlier candidates |
| Categorical statistics | Distinct values, most frequent values (bounded), rare categories, value lengths |
| Target analysis | Task inference (classification/regression), class counts and shares, majority/minority size, imbalance ratio, rare classes, single-class targets, missing labels, identical feature rows with conflicting labels |
| Leakage screen | Features that predict the target almost perfectly (Goodman–Kruskal λ, single-feature ROC AUC, Pearson correlation) |
| Train/test overlap | Test rows that also appear in training; matching features with a different label; schema differences |
| Label review | Out-of-fold logistic-regression predictions (5-fold stratified CV) listing rows to review |
| Corrections | Remove rows without a target, remove exact duplicates, drop empty/constant/copied columns: approved, applied to a copy, audited, downloadable |
| Reports | Strict JSON and a self-contained, script-free HTML report |
| Web UI | Drag-and-drop upload with progress, summary, filterable findings, column explorer, charts, target selection, ML checks, corrections, downloads, light/dark themes, responsive layout |

Not implemented (see [Limitations](#known-limitations) and [Future work](#future-improvements)):
controlled model-impact experiments, Cleanlab integration, imputation as a correction, near-duplicate
detection, and file formats other than CSV.

## Architecture

```
app/
  config.py            Resource limits (env-overridable) and the application version
  main.py              App factory: routes, error handlers, security headers, static frontend
  api/
    routes.py          HTTP endpoints only; heavy work runs in a worker thread
    uploads.py         Bounded, in-memory multipart parsing (uploads never touch disk)
  models/
    schemas.py         Pydantic response contracts (strict JSON: no NaN/Infinity)
  services/            Pure Python; no FastAPI imports
    loader.py          CSV validation and parsing; DatasetError for expected, user-safe failures
    profiler.py        Types, missing values, duplicates, numeric/categorical stats, redundancy
    target.py          Target task inference, class distribution, label conflicts
    leakage.py         Target-leakage screen and train/test overlap
    findings.py        Rules that turn observations into findings; qualitative summary
    analysis.py        Orchestrates stages; a failing stage marks the result "partial"
    label_review.py    Opt-in cross-validated label review (scikit-learn)
    corrections.py     Proposed corrections and approved, audited application
    report.py          JSON report document and escaped HTML rendering
frontend/              index.html, style.css, app.js (no build step, no external assets)
sample_data/           Synthetic demo datasets (see sample_data/README.md)
scripts/               generate_sample_data.py
tests/                 pytest suite (unit, integration, security, determinism)
reports/               Reserved for report artifacts (nothing is written here automatically)
```

Request flow: `routes.py` reads the upload with a byte cap → `loader.load_csv` validates it →
`analysis.run_analysis` runs the profiling, target and findings stages → Pydantic serializes the
`AnalysisResult`.

## Prerequisites

- Python 3.12 or newer is required by the pinned packages (NumPy 2.5.4 requires >=3.12).
  DataSentry has only been tested with Python 3.14.4 on Windows 11.
- A modern browser
- Optional: Node.js, only to run the JavaScript syntax check

## Installation (Windows PowerShell)

```powershell
cd "C:\path\to\dataSentry"
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install -r requirements.txt
```

On macOS or Linux: `python3 -m venv .venv`, `source .venv/bin/activate`, then the same `pip`
command.

## Running the application

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. The FastAPI server also serves the frontend, so there is nothing
else to start. Interactive API documentation is at <http://127.0.0.1:8000/docs> (Swagger UI loads
its assets from a CDN; the application itself does not).

Add `--reload` during development.

## Running the tests

```powershell
python -m pytest
```

Other checks used during development:

```powershell
python -m compileall -q app tests scripts   # Python syntax
node --check frontend/app.js                # JavaScript syntax (requires Node.js)
```

## Example workflow

1. Start the server and open the app.
2. Click **Customer churn (classification)**. The synthetic sample is analyzed with `churned` as
   the target.
3. The summary shows issues in *Completeness* and *Leakage*. Open the high-severity finding: the
   `cancellation_code` feature almost perfectly predicts `churned`, and the finding explains why
   this suggests leakage without proving it.
4. Click a column chip (for example `age`) to open its distribution, outlier candidates and
   related findings.
5. On **ML checks**, run **Label review**, then **Use sample holdout** to find the 20 holdout rows
   that were copied from the training file.
6. On **Corrections**, select the proposed changes, read their implications, tick the approval
   box and apply. Download the corrected CSV and its audit record, or analyze the corrected copy.
7. Download the HTML or JSON report.

## API

All uploads are `multipart/form-data`. Options are form fields (not query parameters), so column
names do not appear in access logs.

| Method | Path | Form fields | Returns |
|---|---|---|---|
| GET | `/api/health` | — | Status, version and active limits |
| POST | `/api/analyze` | `file`, optional `target_column` | `AnalysisResult` JSON |
| POST | `/api/report` | `file`, optional `target_column`, `format` (`json`/`html`), `include_values` (`true`/`false`, default false) | Report as a download |
| POST | `/api/label-review` | `file`, `target_column` | `LabelReviewResult` JSON |
| POST | `/api/train-test-overlap` | `train_file`, `test_file`, optional `target_column` | `TrainTestOverlapResult` JSON |
| POST | `/api/corrections/apply` | `file`, `plan` (JSON: `{"approved": true, "target_column": ..., "steps": [{"operation": ..., "columns": [...]}]}`) | Corrected CSV text and audit record |

Example:

```powershell
curl.exe -F "file=@sample_data/customer_churn.csv" -F "target_column=churned" http://127.0.0.1:8000/api/analyze
```

Errors always have the shape `{"error": "<stable_code>", "message": "<safe text>"}`, with status
400 (malformed request), 413 (size, row or column limit), 415 (not CSV / not multipart), 422
(invalid content or options), 500 (unexpected; no details) or 503 (server busy). Examples of codes:
`empty_file`, `no_data_rows`, `invalid_encoding`, `malformed_csv`, `empty_header`,
`duplicate_header`, `too_many_rows`, `too_many_columns`, `file_too_large`, `unsupported_format`,
`unknown_target_column`, `approval_required`, `invalid_plan`.

### Analysis result

`AnalysisResult` (see `app/models/schemas.py`) contains `dataset` (name, size, SHA-256), `settings`,
`stages` (each `completed`, `failed` or `skipped`), `status` (`complete` or `partial`), `overview`,
`columns` (one profile per column, in file order), `duplicates`, `redundancy`, `target`,
`findings`, `summary`, `corrections` (proposals only) and `limitations`. A section is `null` when
its stage did not complete.

Each finding has a stable `code`, `kind` (`likely_issue`, `potential_issue`, `observation`,
`inconclusive`), `severity` (`high`, `medium`, `low`, `info`), `category`, `title`, `explanation`,
`why_it_matters`, `recommendation`, optional `limitations`, affected `columns`, `evidence`
(supporting statistics) and an optional `correction` id. Findings are sorted by severity, kind,
category, code and columns, so identical input always gives identical output.

## Supported input and resource limits

- **Format:** UTF-8 CSV (a byte-order mark is accepted) with a header row, comma separator and
  standard double-quote quoting. Excel, PDF, archives and binary files are rejected with a message.
- **Header rules:** column names must be non-empty and unique. Duplicates are detected before
  pandas would silently rename them.
- **Structure:** every row must have as many fields as the header. Blank lines are skipped, so in a
  one-column file an empty value on its own line is treated as a blank line. Single fields larger
  than 128 KB are rejected.
- **Missing values:** empty cells and pandas' default tokens (`NA`, `N/A`, `null`, `NaN`, `None`,
  and similar) are treated as missing.

| Limit | Default | Environment variable |
|---|---|---|
| Upload size per file | 10 MB (10,485,760 bytes) | `DATASENTRY_MAX_UPLOAD_BYTES` |
| Data rows | 200,000 | `DATASENTRY_MAX_ROWS` |
| Columns | 500 | `DATASENTRY_MAX_COLUMNS` |
| Concurrent analyses | 2 (others wait up to 30 s, then get 503) | `DATASENTRY_MAX_CONCURRENT_ANALYSES` |
| Label review rows | 20,000 | `DATASENTRY_MAX_LABEL_REVIEW_ROWS` |

Timings measured once on the development machine: a 7.4 MB file with 200,000 rows and 7 columns
loads in about 0.2 s and is analyzed in about 3 s; a 500-column file takes about 1 s; label review
on 20,000 rows takes about 1 s. These are indicative only.

## Diagnostic methodology

Every threshold is a named constant in the module that uses it, and the same list is embedded in
each report's *Methodology* section.

- **Type inference.** Numeric and boolean types come from the CSV parser. A text column is
  *boolean* if every value is `true`/`false` (any case), *datetime* if every value is an ISO 8601
  date or datetime, *categorical* if it has at most 50 distinct values or a distinct ratio of at
  most 0.5, and otherwise *text*. Other date formats (for example `01/02/2024`) stay categorical
  because they are ambiguous.
- **Missing values.** Columns missing at least 5% of values get their own finding (medium severity
  from 50%); smaller amounts are grouped into one observation. Missing target labels are reported
  only by the target checks.
- **Duplicates.** A duplicate row is an exact repeat of an earlier row across all columns,
  compared after parsing (`1` and `1.0` in a numeric column are equal), with missing values equal
  to each other. Only repeats are counted, not first occurrences. Medium severity from 5% of rows.
  Duplicates are never removed automatically.
- **Constant / near-constant.** Constant means at most one distinct non-missing value. Near-constant
  means the most frequent value covers at least 95% of at least 20 non-missing values (an
  observation, because rare-event flags are legitimate).
- **Identifier-like / high cardinality.** Identifier-like means at least 20 rows, no missing
  values, a distinct value in every row, and integer or string values. High cardinality means a
  categorical or text column with at least 50 distinct values covering at least half of its values.
  Both are observations; column names are never used.
- **Redundancy.** Identical columns are compared exactly. Numeric pairs with |Pearson r| ≥ 0.99 over
  at least 10 rows are observations. Screening is limited to 50 numeric columns, and the summary
  says when it was skipped.
- **Outlier candidates.** Tukey fences (Q1 − 1.5·IQR, Q3 + 1.5·IQR), computed with at least 10
  finite values and a non-zero IQR. Otherwise the screen is marked unavailable or inconclusive.
  Candidates are observations for review, never errors.
- **Numeric edge cases.** NaN is missing. ±∞ is counted separately and excluded from statistics
  (an `infinite_values` finding). The standard deviation needs at least 2 values. Undefined
  statistics are `null`.
- **Categories.** Up to 10 most frequent values are listed (ties alphabetical, values clipped to
  200 characters). Rare categories (under 1% of values) are evaluated only with at least 100
  values and at most 1,000 categories. Variants are values that become equal after trimming,
  collapsing whitespace and ignoring case. "Numbers stored as text" means at least 80% but not all
  values of a text column parse as numbers.
- **Target.** The target is never guessed. Boolean and non-numeric targets are classification.
  Integer-valued targets with at most 20 distinct values are classification (with a note that they
  may be quantities). Other numeric targets are regression. Up to 50 classes are listed. Rare
  classes have fewer than 5 examples (too few for 5-fold stratified CV). Imbalance (largest ÷
  smallest class) is an *observation* from 3:1 and never a defect by itself. Rows with identical
  features but different labels are reported as label conflicts.
- **Leakage screen** (needs at least 20 labeled rows). For classification, a feature that repeats
  values (at most one distinct value per two rows, 80% of rows in groups of two or more) with
  Goodman–Kruskal λ ≥ 0.8, meaning it removes at least 80% of the errors of always guessing the
  majority class; and, for binary targets, a numeric feature whose single-feature ROC AUC is
  ≥ 0.99 or ≤ 0.01. For regression, |Pearson r| ≥ 0.99. These are prompts to verify that the
  feature is available at prediction time. A strong association does not prove leakage, and leakage
  can exist without any of these signals.
- **Train/test overlap.** Rows are compared on shared columns using 64-bit hashes of parsed values
  (integer and float columns are aligned). A test row whose features match training but whose
  label does not is reported separately.
- **Label review.** Columns that are identifier-like, constant, empty, text, datetime,
  high-cardinality (more than 50 categories) or flagged by the leakage screen are excluded.
  Numeric features are median-imputed and standardized, and categoricals are one-hot encoded,
  inside a scikit-learn `Pipeline`, so preprocessing is fitted on training folds only. A
  `LogisticRegression` is evaluated with `StratifiedKFold(5, shuffle=True, random_state=0)` using
  `cross_val_predict`. Rows whose out-of-fold prediction differs from the given label are listed,
  lowest given-label probability first (up to 50). Out-of-fold accuracy, balanced accuracy and the
  majority-class baseline are reported so you can judge whether the model is informative. Classes
  with fewer than 5 examples are excluded. Labels are never changed.

### Why there is no score

Weighting missing values against duplicates, leakage or label noise would be arbitrary and
task-dependent, and an aggregate could let a high number hide one severe problem. Instead the
summary reports each category as `issue`, `review`, `pass` or `not_evaluated`, lists the checks that
did not run, and counts findings by severity. Nothing in DataSentry predicts model accuracy.

## Reports

- **JSON** (`ReportDocument`): `metadata` (tool version, UTC generation time, value-inclusion
  setting, serialization policy, privacy note), the full `analysis` and the `methodology`. The
  output is strict JSON: NaN and infinity are never emitted, undefined statistics are `null`, and
  floats are rounded to 6 decimals. Apart from `generated_at`, identical inputs and settings give
  identical reports.
- **HTML:** a single self-contained file with an executive summary, dataset overview, all findings
  with evidence and next steps, target analysis, column diagnostics, suggested corrections,
  methodology, limitations and stage status. Every dynamic string is HTML-escaped, and the page
  declares `Content-Security-Policy: default-src 'none'`, so it cannot run scripts or load
  resources.
- **Values in reports:** reports never contain dataset rows. By default they also omit frequent
  category values and spelling variants. Tick *Include category values* (or send
  `include_values=true`) to include them. Column names, statistics and target class labels are
  always included.

## Security and privacy

- Uploads are parsed in memory by a size-capped multipart reader (`app/api/uploads.py`). Oversized
  bodies are rejected while streaming, and files are never written to temporary files or kept after
  the request. A test fails if Starlette tries to spool an upload to disk.
- Uploaded content is only parsed as CSV: no `eval`, pickle, Excel parsing or code execution.
- Client filenames are reduced to a safe basename used for display and download names only, never
  as a filesystem path. Static files are served by Starlette's `StaticFiles`, and tests check that
  path traversal returns 404.
- Error responses use fixed templates with no cell values and no tracebacks. Unexpected exceptions
  return a generic 500. Logs record only the exception type, stage name and request path, because
  library exception messages can quote data.
- The frontend inserts dataset strings with `textContent`/text nodes only, and the app is served
  with a strict Content-Security-Policy (`script-src 'self'`, no inline scripts), `nosniff`,
  `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer`.
- Corrections require `approved: true`, never modify the upload, and return an audit record with
  input and output SHA-256 hashes.

Scope of the security review: the upload path, CSV parsing, error handling, logging, HTML
rendering (UI and report), static file serving, serialization and the cost of every diagnostic.
It was a code review backed by regression tests, not a penetration test, and the application has
no authentication. Bind it to `127.0.0.1` (as above) rather than a public interface. Request bodies
are buffered before the concurrency limit applies, so many simultaneous large uploads can still use
a lot of memory. The corrected CSV contains your own data unchanged; if it holds cells starting with
`=`, `+`, `-` or `@`, spreadsheet programs may interpret them as formulas.

## Sample data

`sample_data/` contains three synthetic datasets with deliberately planted problems:
`customer_churn.csv` (classification), `customer_churn_holdout.csv` (overlapping holdout) and
`sensor_energy.csv` (regression). `sample_data/README.md` lists each planted issue and the finding
it should produce. Regenerate them with `python scripts/generate_sample_data.py`.

## Known limitations

- CSV only: comma-separated, UTF-8. Other delimiters and encodings are rejected rather than guessed.
- Only exact duplicates and exact train/test matches are detected, not near-duplicates or related
  records (for example the same customer at two dates).
- Datetime recognition is ISO 8601 only. Booleans are recognized as `true`/`false`, not `yes`/`no`.
- Heuristics with fixed thresholds can produce false positives and false negatives; every finding
  says what it is based on.
- The leakage screen catches only single features with near-perfect association. It cannot detect
  temporal leakage, leakage through feature engineering, or leakage spread across several columns.
- Label review uses one linear model; a weak model makes its disagreements uninformative (the UI
  warns when balanced accuracy is below 0.7).
- The server keeps no state: each action re-uploads the file from the browser, so every analysis
  is recomputed from scratch.
- Not implemented: controlled model-impact experiments, Cleanlab-based label analysis, imputation
  corrections (imputation belongs inside a training pipeline, where it can be fitted on training
  data only), authentication and multi-user deployment.

## Future improvements

- Reproducible model-impact experiments (for example duplicate contamination across a split, or
  controlled label noise) with a fixed baseline, isolated test set and multiple seeds.
- Group-aware and temporal train/test checks (an entity or time column chosen by the user).
- Near-duplicate detection (normalized text, numeric tolerance).
- Configurable missing-value tokens, delimiter and encoding.
- Optional Cleanlab integration for label issues, once its dependency footprint is justified.
- Frontend unit tests and an automated browser test in CI.
