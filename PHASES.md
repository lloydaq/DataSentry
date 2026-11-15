# DataSentry — phases

The build plan after milestones 1–6 (see `CLAUDE.md` → Implementation status). Build **one phase
at a time**. Each phase must be independently testable and must leave the full suite green.

Rules that apply to every phase:

- Diagnostics live in `app/services/` and never import FastAPI.
- Thresholds are named constants, mirrored in `report.METHODOLOGY` and the README.
- Findings use `observation` / `potential_issue` / `likely_issue` / `inconclusive` by strength of
  evidence. No invented results, and no score presented as a probability.
- Uploads stay in memory. Nothing new is persisted, and there are no external calls.
- Every phase ships with tests for normal, empty, malformed, degenerate and adversarial input.

Status key: ☐ not started · ◐ in progress · ☑ done

---

## Phase 0 — Housekeeping and CI ◐

**Goal:** a clean repository and automated proof that it works.

- `.gitignore` entries for the AI-agent tool folders and impeccable session state.
- GitHub Actions workflow (`contents: read`, no secrets) that runs pytest, `compileall` and
  `node --check` on the frontend scripts.
- Fix the stale "no commits yet" line in `CLAUDE.md`.
- Optional LICENSE. If added, also add the README badge and section. Add a CI badge only after a
  green run on GitHub.

**Done when:** `git status` is clean apart from intentional files, and CI passes on GitHub.

## Phase 1 — Frontend and browser tests ☐

**Goal:** the UI is protected by tests the same way the backend is.

- Unit tests for the pure `app.js` helpers (`put()`, `h()`, formatters), run with Node's built-in
  test runner. No new framework.
- One end-to-end browser smoke test: load a sample → findings render → ML checks → theme switch
  → zero CSP violations and zero stray `"null"` text nodes.
- Both run in CI.

**Done when:** a regression like the `"null"` text bug would fail CI.

## Phase 2 — Configurable input ☐

**Goal:** real-world CSVs load without pre-cleaning.

- Request options for delimiter (`,` `;` `\t` `|`), encoding (UTF-8, UTF-8-SIG, Latin-1) and
  missing-value tokens (e.g. `NA`, `?`, `-999`).
- Every option is allow-listed on the server. Token count and length are capped.
- The chosen options are echoed in the result and the report, for reproducibility.

**Done when:** semicolon and Latin-1 fixtures load correctly, and invalid options get fixed-template
errors.

## Phase 3 — Split Doctor (group-aware and temporal splits) ☐ *(distinctive)*

**Goal:** catch the split mistakes that inflate validation scores. These are among the most common
real ML failures, and generic profilers rarely check them.

- The user names an optional **entity column** (e.g. `customer_id`) and/or a **time column**.
- **Train/test overlap:**
  - the same entity appearing on both sides;
  - test rows dated before the latest training row (temporal leakage).
- **Single dataset:** a split recommendation (random / stratified / group / time-based), each with
  the evidence that led to it, e.g. "38% of entities have more than one row → a random split
  would put the same entity in train and test".
- Phrase results as potential issues and recommendations, never as proof.

**Done when:** synthetic fixtures with planted entity and temporal leakage are flagged, and clean
fixtures are not.

## Phase 4 — Dataset Diff (version-to-version changes) ☐ *(distinctive)*

**Goal:** answer "what changed between v1 and v2 of this dataset?" before retraining.

- Upload two CSVs. Report schema changes (columns added, removed, renamed-looking, or retyped),
  row-count change, new or vanished categories, missing-rate shifts and distribution shift per
  column.
- Distribution shift uses documented, bounded statistics (KS for numeric columns, PSI with fixed
  binning for categorical ones). Values are reported as statistics, not probabilities, and
  thresholds are named constants.
- Comparing findings between the two versions shows each issue as **new / resolved / persisting**.

**Done when:** planted drift fixtures produce the expected changes, identical files produce "no
changes", and output is deterministic.

## Phase 5 — Data Contract export and check ☐ *(distinctive)*

**Goal:** turn one good dataset into guardrails for the next one.

- Export an inferred contract from an analyzed dataset: column types, nullability, numeric
  ranges, allowed categories, uniqueness and the target column. Output is a plain JSON document
  with a version field.
- The user reviews and edits it, since an inferred contract is a starting point, not truth.
- Upload a CSV together with a contract: every violation becomes a finding with evidence (counts
  and row positions only, never cell values in errors).
- Contracts are validated against a strict Pydantic schema and treated as untrusted input.

**Done when:** a contract round-trips (export → check the same file → no violations), and each
violation type has a test.

## Phase 6 — Quality gate CLI ☐ *(distinctive)*

**Goal:** use DataSentry inside a data pipeline, not only in a browser.

- `python -m app.cli check data.csv [--target y] [--contract c.json] [--fail-on likely_issue]`
- It reuses `app/services` directly, with no server and the same limits.
- It writes the JSON or HTML report to a path the user chooses and exits non-zero when findings
  at or above `--fail-on` exist.
- Include a documented GitHub Actions snippet for gating a dataset in CI.

**Done when:** exit codes are tested for clean, warning and failing datasets, and output matches
the API result exactly.

## Phase 7 — Datasheet draft ☐ *(distinctive)*

**Goal:** speed up dataset documentation without pretending to know what only humans know.

- Generate a Markdown/HTML datasheet draft, loosely following "Datasheets for Datasets":
  - **auto-filled from the analysis:** composition, missing data, target distribution, known
    findings;
  - **marked "to be completed by a person":** motivation, collection process, consent, intended
    use.
- Never fabricate provenance or intent.

**Done when:** every auto-filled field traces back to a value in the analysis result, and
human-only fields are always left blank.

## Phase 8 — Finding review log ☐

**Goal:** an auditable record of what a person decided about each finding.

- In the UI, mark a finding *acknowledged*, *accepted risk* or *fixed upstream*, with a short note.
- Decisions are kept in the page session only, included in the exported report, and can be
  re-imported with that report. Nothing is stored on the server.
- Notes are untrusted text: `textContent` only, escaped in the HTML report.

**Done when:** decisions survive the export → import round trip, and the HTML report escapes notes.

## Phase 9 — Near-duplicate detection ☐

**Goal:** find rows that are duplicates in practice but not byte-identical.

- Normalized text (case, whitespace, punctuation) plus numeric tolerance on selected columns.
- Bounded with a `*_LIMIT` constant and blocking to avoid O(n²). Findings are potential issues,
  and each gives example row positions.

## Phase 10 — Reproducible model-impact experiments ☐ *(flagship)*

**Goal:** measure what an issue actually costs a model, instead of asserting it.

- Experiments include:
  - train with vs without cross-split duplicates;
  - with injected label noise at fixed rates;
  - with vs without a suspected leaky feature.
- Fixed baseline model, isolated test set, multiple fixed seeds. Report the mean and spread,
  never a single cherry-picked run.
- Bounded runtime, opt-in. Results are labeled as experiments on this dataset, not general
  claims.

**Done when:** results are bit-for-bit reproducible across runs, and the planted leakage fixture
shows the expected score inflation.

## Phase 11 — Optional Cleanlab integration ☐

Only if its dependency footprint is justified against Python ≥ 3.12 support and install size. It
must be an optional extra, never a hard requirement.

---

### Suggested order

0 → 1 lay the foundation. Then **3 (Split Doctor)** and **6 (CLI)** give the most practical value
for the effort. **4, 5 and 7** make DataSentry distinct from generic profilers. **10** is the
portfolio centerpiece once the rest is solid.
