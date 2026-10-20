# DataSentry — project instructions

DataSentry is a local-first dataset diagnostics tool for ML practitioners, built as a serious
ML-engineering portfolio project. Workflow: CSV upload → validation → profiling → explainable
findings → interactive report → optional, explicitly approved corrections. Prioritize correctness,
reproducibility, explainability, security and maintainability over feature count.

The README documents usage, the API, every threshold and known limitations. Keep it accurate when
behavior changes; do not duplicate it here.

## Commands (Windows PowerShell, repository root)

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt   # only when requirements change
.\.venv\Scripts\python.exe -m pytest                               # full suite
.\.venv\Scripts\python.exe -m compileall -q app tests scripts      # Python syntax
node --check frontend/app.js                                       # JS syntax
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe scripts\generate_sample_data.py         # deterministic (seed 42)
```

Environment: Python 3.14.4 venv in `.venv/` (pins need ≥3.12). Reuse it; do not upgrade or
reinstall packages without a reason. Dependencies are pinned in `requirements.txt`; add one only
with a concrete benefit and after checking it supports the project's Python version.

## Architecture

Keep these boundaries. `app/services/` and `app/models/` must never import FastAPI/Starlette or
`app.api`.

| Path | Responsibility |
|---|---|
| `app/config.py` | `APP_VERSION` (single source of the version) and `Limits` (env-overridable resource limits) |
| `app/__init__.py` | Package docstring; re-exports `__version__` from config |
| `app/main.py` | `create_app()`: router, error handlers, security headers/CSP, static frontend and `/samples` |
| `app/api/routes.py` | HTTP endpoints only; CPU work runs in a thread behind a concurrency semaphore |
| `app/api/uploads.py` | Size-capped, in-memory multipart parsing (uploads never spool to disk) |
| `app/models/schemas.py` | Pydantic contracts; `allow_inf_nan=False`, so outputs are strict JSON |
| `app/services/loader.py` | CSV validation/parsing; `DatasetError` for expected, user-safe failures |
| `app/services/profiler.py` | Types, missing values, duplicates, numeric/categorical stats, redundancy |
| `app/services/target.py` | Target task inference, class distribution, label conflicts |
| `app/services/leakage.py` | Single-feature leakage screen; train/test overlap |
| `app/services/findings.py` | Rules turning observations into findings; qualitative summary (no score) |
| `app/services/analysis.py` | Stage orchestration; a failed stage makes the result `partial` |
| `app/services/label_review.py` | Opt-in cross-validated label review (scikit-learn) |
| `app/services/corrections.py` | Correction proposals; approved application to a copy with audit trail |
| `app/services/report.py` | JSON report document and escaped, script-free HTML report |
| `frontend/` | `index.html`, `style.css`, `app.js` (UI; DOM appends go through `put()`/`h()`, which skip nulls), `theme.js` (applies the saved theme before paint; key `datasentry-theme`), `kinetic-grid.js` (canvas background); no build step, no external assets |
| `tests/` | pytest: unit, API integration, security boundaries, determinism (`conftest.py` holds shared helpers) |
| `docs/` | README artwork (`assets/*.svg`) and real app screenshots (`screenshots/*-light.png`, `*-dark.png`) |
| `sample_data/` | Synthetic demo CSVs from `scripts/generate_sample_data.py`; planted issues listed in its README |
| `reports/` | Reserved for report artifacts. Preserve it and its contents; nothing writes here automatically |

## Implementation status

Implemented and tested: everything in milestones 1–5 (loader, schemas, core and extended
diagnostics, target analysis, findings and summary, API, frontend, JSON/HTML reports, hardening)
plus, from milestone 6, the leakage screen, train/test overlap, label review and approved
corrections.

Not implemented (do not describe as existing): reproducible model-impact experiments, Cleanlab,
imputation as a correction, near-duplicate detection, non-CSV formats, authentication. Build them
only when asked, one independently testable milestone at a time.

## Diagnostic integrity

- Separate observations from problems. Finding `kind` is `likely_issue`, `potential_issue`,
  `observation` or `inconclusive`; choose it by the strength of evidence.
- Class imbalance, outliers, missing values, high cardinality and identifier-like columns are not
  defects by themselves. Correlation does not prove leakage; model disagreement does not prove a
  wrong label.
- Every finding needs a stable `code`, evidence, why it matters, a next step and, where relevant,
  limitations. Thresholds are named module constants and are mirrored in
  `report.METHODOLOGY` and the README — update all three together.
- No numeric quality score or confidence value without a documented, defensible method. Undefined
  metrics are `null`/"unavailable", never fabricated. Never invent benchmark or experiment results.
- Output must be deterministic: explicit sort orders, fixed seeds, rounded floats.

## Security and resources

- Uploads are untrusted. Enforce size/row/column limits server-side; the frontend's checks are
  convenience only. Bound every expensive diagnostic (see the `*_LIMIT`/`MAX_*` constants).
- Never execute uploaded content (`eval`, `exec`, pickle, Excel/formula parsing). Never persist
  uploads. Never use client filenames as paths (`loader.sanitize_filename` is display-only).
- Error messages are fixed templates without cell values; no tracebacks to clients. Log only
  exception types, stage names and paths — library exception text can contain data.
- Frontend: insert untrusted strings with `textContent`/text nodes only; never `innerHTML`. The CSP
  forbids inline scripts. HTML reports escape everything via `report._e`.
- Never modify the original dataset or apply a correction without `approved: true`.
- ML checks: fit preprocessing inside the CV pipeline; keep test data isolated from decisions.

## Testing

- Add or update focused tests with every behavior change: normal input, empty/malformed input,
  boundaries, unusual names and types, degenerate datasets, invalid targets, API errors, security
  handling and determinism. Use small synthetic data only.
- Tests must assert behavior, not just execution. Never weaken, skip or delete a test to get a pass.
- Report only checks you actually ran, with their real results. Investigate failures and say
  whether they are regressions or pre-existing.

## Workflow, Graphify and Git safety

1. Inspect the relevant code, call paths and `git status` before editing.
2. Make the smallest coherent change; then run focused tests, then the full suite.
3. Review the diff for accidental or unrelated edits, and report changes, results and limitations.

- Graphify (`graphify update app --no-cluster`, then `graphify god-nodes` / `graphify affected "X"`)
  is a navigation aid, not proof of correctness. Its output (`graphify-out/`) stays local and
  git-ignored.
- The repository has no commits yet. Do not commit, push, reset, clean or rewrite history unless
  explicitly asked. Never discard user changes. Preserve `reports/` and `sample_data/`. Keep
  `.env` and other secrets out of version control. Do not touch other repositories.
