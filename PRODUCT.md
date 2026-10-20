# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: ML practitioners who are about to train or evaluate a model on a tabular CSV and want to
find data problems first. They are technical, short on time, and need to decide quickly what to
fix, what to investigate and what is merely worth knowing.

Secondary: portfolio reviewers (recruiters, hiring managers, interviewers). DataSentry is an
engineering student's ML-engineering portfolio project, so the product itself must demonstrate
rigor. This audience is served by the product being genuinely useful to the primary user, not by
separate showcase material.

## Product Purpose

DataSentry profiles an uploaded CSV and explains potential data-quality problems before they
reach a model. Workflow: CSV upload → validation → profiling → explainable findings → interactive
report → optional, explicitly approved corrections.

Success: a practitioner understands within minutes which issues could hurt their model, why, and
what to do next, and trusts the output because every claim shows its evidence.

## Positioning

**Evidence over verdicts.** Every finding states its evidence, why it matters, the recommended
next step and its limitations. Observations (class imbalance, outliers, high cardinality) are kept
separate from likely and potential problems, and inconclusive checks are labeled as such.
DataSentry deliberately refuses to produce a single numeric "data quality score", because any
weighting would be arbitrary and could hide a severe individual problem. Neighboring tools that
emit scores or bare pass/fail verdicts cannot truthfully claim this.

## Operating Context

- Run locally: a FastAPI server on `127.0.0.1` serves both the API and the browser UI.
- Input is one UTF-8 CSV at a time (10 MB, 200,000 rows and 500 columns by default). Opt-in checks
  take a second file (train/test overlap) or a selected target column.
- Outputs the practitioner takes away: downloadable JSON and HTML reports, a corrected CSV copy and
  its audit record.
- Typical session: upload or pick a synthetic sample, read the summary, drill into findings and
  columns, select a target, run opt-in ML checks, optionally apply approved corrections, download
  a report.

## Capabilities and Constraints

Implemented: CSV validation; type inference; missing values; exact duplicates; column-quality,
consistency, numeric and categorical diagnostics; target analysis; single-feature leakage screen;
train/test overlap; cross-validated label review; approved corrections; JSON/HTML reports; a
dashboard UI with light and dark themes.

Not implemented (never present as existing): model-impact experiments, Cleanlab, imputation as a
correction, near-duplicate detection, non-CSV formats, authentication.

Constraints (chosen by the assistant at the user's request, marked *delegated*):

- *Delegated:* local-only use; no design for hosted or multi-user deployment.
- *Delegated:* no external assets (no CDNs, web fonts or remote images). The app's
  Content-Security-Policy already enforces this, and the UI must work offline.
- Uploads are untrusted and never stored; dataset strings are rendered as text, never HTML.
- No paid APIs, LLMs, cloud services, accounts or databases in the core product.

Terminology: *finding*, *kind* (likely issue / potential issue / observation / inconclusive),
*severity* (high / medium / low / info), *category*, *target column*, *correction*, *audit record*.

Open decision: whether a public hosted demo will exist. Undecided; it would require revisiting the
local-only constraint.

## Brand Commitments

Name: DataSentry. Voice: precise, calm, evidence-led and honest about uncertainty. Findings say
"potential" or "likely", never "confirmed", unless the evidence supports it. No logo, mascot or
other binding visual identity has been committed.

## Evidence on Hand

- Synthetic demo datasets with documented, deliberately planted issues: `sample_data/`
  (`customer_churn.csv`, `customer_churn_holdout.csv`, `sensor_energy.csv`; see its README).
- An automated test suite (160 tests at the time of writing) and reproducible sample generation.
- Absent, and not to be fabricated: users, testimonials, adoption figures, benchmarks against other
  tools, measured model-accuracy improvements, and real or personal datasets.

## Product Principles

1. **Show the evidence.** No claim without the statistics behind it and its limitations.
2. **Separate fact from judgment.** Observations, potential problems, likely problems and
   inconclusive results stay visibly distinct.
3. **Never decide for the user silently.** Nothing is changed without explicit approval; the
   original data is never modified.
4. **Honest about absence.** Checks that did not run, or could not compute, say so rather than
   implying a clean result.
5. **Private by construction.** The data stays on the user's machine and out of logs and reports
   unless the user opts in.

## Accessibility & Inclusion

*Delegated:* WCAG 2.2 AA is the required standard for every surface: contrast in both light and
dark themes, full keyboard operation, visible focus, screen-reader-meaningful charts and status
messages, and respect for `prefers-reduced-motion`.
