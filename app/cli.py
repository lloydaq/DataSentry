"""Command-line quality gate: analyze a CSV without a server and fail a pipeline on findings.

    python -m app.cli check data.csv --target label --fail-on likely_issue --report report.html

It runs the same services, limits and report code as the API, so a result written here is the same
document the API returns for the same file and options. Exit codes:

    0  the gate passed
    1  the gate failed: at least one finding is at or above the threshold
    2  usage or input error (bad arguments, unreadable or invalid file, invalid contract)
    3  the analysis was incomplete (a stage failed), so the gate cannot vouch for the file

Dataset strings are printed with control characters replaced, so a crafted column name cannot
drive the terminal. Errors print fixed messages, never tracebacks or cell values.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.config import APP_VERSION, Limits
from app.models.schemas import AnalysisResult, ContractCheckResult, Finding, FindingKind, Severity
from app.services import contract as contracts
from app.services import report
from app.services.analysis import run_analysis
from app.services.loader import DELIMITERS, ENCODINGS, DatasetError, load_csv, parse_options

EXIT_PASSED, EXIT_FAILED, EXIT_USAGE, EXIT_INCOMPLETE = 0, 1, 2, 3

# Gate order: observations describe the data and never fail the gate.
KIND_RANK = {
    FindingKind.observation: 0,
    FindingKind.inconclusive: 1,
    FindingKind.potential_issue: 2,
    FindingKind.likely_issue: 3,
}
FAIL_ON = {"likely_issue": 3, "potential_issue": 2, "inconclusive": 1, "never": None}
SEVERITY_RANK = {Severity.info: 0, Severity.low: 1, Severity.medium: 2, Severity.high: 3}
GATE_LIST_LIMIT = 20  # gating findings printed in text mode


class UsageError(Exception):
    """A problem with the command line; the message is safe to print."""


def _safe(text: object) -> str:
    """Printable form of a dataset-derived string: control characters become U+FFFD."""
    return "".join(
        ch if ch == " " or (ord(ch) >= 32 and not 0x7F <= ord(ch) <= 0x9F) else "�"
        for ch in str(text)
    )


def _read(path: Path, limits: Limits, label: str) -> bytes:
    if not path.is_file():
        raise UsageError(f"The {label} '{_safe(path)}' does not exist or is not a file.")
    with path.open("rb") as handle:
        return handle.read(limits.max_upload_bytes + 1)  # one extra byte lets the loader report "too large"


def gating(findings: Sequence[Finding], fail_on: str, min_severity: str) -> list[Finding]:
    """Findings at or above the threshold: kind at least ``fail_on`` and severity at least
    ``min_severity``. ``fail_on='never'`` gates nothing."""
    floor = FAIL_ON[fail_on]
    if floor is None:
        return []
    sev_floor = SEVERITY_RANK[Severity(min_severity)]
    return [
        f for f in findings
        if KIND_RANK[f.kind] >= floor and SEVERITY_RANK[f.severity] >= sev_floor
    ]


def _write_report(result: AnalysisResult, path: Path, include_values: bool) -> None:
    suffix = path.suffix.lower()
    if suffix not in (".json", ".html"):
        raise UsageError("--report must end in .json or .html.")
    doc = report.build_report(result, include_values)
    body = report.render_html(doc) if suffix == ".html" else doc.model_dump_json(indent=2)
    path.write_text(body, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="DataSentry quality gate: analyze a CSV locally and exit non-zero on findings.",
    )
    parser.add_argument("--version", action="version", version=f"DataSentry {APP_VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check",
        help="analyze a CSV and apply the gate",
        description="Exit codes: 0 passed, 1 gate failed, 2 usage or input error, "
        "3 analysis incomplete.",
    )
    check.add_argument("csv", type=Path, help="the CSV file to analyze")
    check.add_argument("--target", help="target column, for target and leakage checks")
    check.add_argument("--contract", type=Path, help="data contract (JSON) to check the file against")
    check.add_argument(
        "--fail-on", choices=list(FAIL_ON), default="likely_issue",
        help="lowest finding kind that fails the gate (default: likely_issue; never = report only)",
    )
    check.add_argument(
        "--min-severity", choices=[s.value for s in Severity], default="info",
        help="ignore findings below this severity when gating (default: info, i.e. all)",
    )
    check.add_argument("--report", type=Path, help="write the report here (.json or .html)")
    check.add_argument(
        "--include-values", action="store_true",
        help="include frequent category values in the report (omitted by default)",
    )
    check.add_argument("--result", type=Path, help="write the raw analysis result (JSON) here")
    check.add_argument("--format", choices=["text", "json"], default="text", help="stdout format")
    parsing = check.add_argument_group("parsing options (with --contract, the contract's own options are used)")
    parsing.add_argument("--delimiter", choices=list(DELIMITERS))
    parsing.add_argument("--encoding", choices=list(ENCODINGS))
    parsing.add_argument("--missing-values", help="comma-separated extra missing-value tokens")
    return parser


def _check(args: argparse.Namespace, limits: Limits) -> tuple[int, dict]:
    spec = None
    if args.contract is not None:
        if args.delimiter or args.encoding or args.missing_values:
            raise UsageError(
                "With --contract the file is read with the contract's parsing options; "
                "remove --delimiter, --encoding and --missing-values."
            )
        spec = contracts.parse_contract(_read(args.contract, limits, "contract"), limits)
        options = contracts.contract_options(spec)
    else:
        options = parse_options(args.delimiter, args.encoding, args.missing_values)

    dataset = load_csv(_read(args.csv, limits, "CSV file"), limits, args.csv.name, options)
    result = run_analysis(dataset, args.target)
    checked: ContractCheckResult | None = contracts.check_contract(dataset, spec) if spec else None

    if args.result is not None:
        args.result.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    if args.report is not None:
        _write_report(result, args.report, args.include_values)

    findings = list(result.findings) + (list(checked.findings) if checked else [])
    blocking = gating(findings, args.fail_on, args.min_severity)
    if blocking:
        code = EXIT_FAILED
    elif result.status != "complete":
        code = EXIT_INCOMPLETE
    else:
        code = EXIT_PASSED

    counts = {s.value: 0 for s in Severity}
    for f in findings:
        counts[f.severity.value] += 1
    summary = {
        "tool_version": APP_VERSION,
        "file": result.dataset.filename,
        "sha256": result.dataset.sha256,
        "n_rows": result.dataset.n_rows,
        "n_columns": result.dataset.n_columns,
        "analysis_status": result.status,
        "overall": result.summary.status,
        "gate": {
            "fail_on": args.fail_on,
            "min_severity": args.min_severity,
            "passed": code == EXIT_PASSED,
            "exit_code": code,
        },
        "severity_counts": counts,
        "gating_findings": [
            {"code": f.code, "kind": f.kind.value, "severity": f.severity.value,
             "title": f.title, "columns": f.columns}
            for f in blocking
        ],
        "contract": None if checked is None else {
            "passed": checked.passed,
            "n_rules_checked": checked.n_rules_checked,
            "n_violations": len(checked.violations),
        },
        "incomplete_stages": [s.name for s in result.stages if s.status != "completed"],
        "report": str(args.report) if args.report else None,
        "result": str(args.result) if args.result else None,
    }
    return code, summary


def _print_text(summary: dict) -> None:
    g = summary["gate"]
    c = summary["severity_counts"]
    print(f"DataSentry {summary['tool_version']} - {_safe(summary['file'])} "
          f"({summary['n_rows']} rows x {summary['n_columns']} columns)")
    print(f"Analysis: {summary['analysis_status']}; overall: {summary['overall'].replace('_', ' ')}")
    print(f"Findings: {c['high']} high, {c['medium']} medium, {c['low']} low, {c['info']} info")
    if summary["contract"] is not None:
        k = summary["contract"]
        print(f"Contract: {'passed' if k['passed'] else 'failed'} "
              f"({k['n_violations']} violation(s), {k['n_rules_checked']} rules checked)")
    if summary["incomplete_stages"]:
        print(f"Incomplete stages: {', '.join(summary['incomplete_stages'])}")
    scope = "never fails" if g["fail_on"] == "never" else \
        f"fails on {g['fail_on'].replace('_', ' ')} or stronger, severity {g['min_severity']} or higher"
    verdict = {EXIT_PASSED: "PASSED", EXIT_FAILED: "FAILED", EXIT_INCOMPLETE: "INCOMPLETE"}[g["exit_code"]]
    print(f"Gate ({scope}): {verdict}")
    blocking = summary["gating_findings"]
    for f in blocking[:GATE_LIST_LIMIT]:
        cols = f" [{', '.join(_safe(x) for x in f['columns'])}]" if f["columns"] else ""
        print(f"  - {f['severity']:<6} {f['kind']:<15} {f['code']}: {_safe(f['title'])}{cols}")
    if len(blocking) > GATE_LIST_LIMIT:
        print(f"  ... and {len(blocking) - GATE_LIST_LIMIT} more")
    for key, label in (("report", "Report"), ("result", "Result")):
        if summary[key]:
            print(f"{label} written to {_safe(summary[key])}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)  # argparse exits with 2 on usage errors
    try:
        code, summary = _check(args, Limits.from_env())
    except (UsageError, DatasetError) as exc:
        print(f"error: {_safe(getattr(exc, 'message', exc))}", file=sys.stderr)
        return EXIT_USAGE
    except OSError as exc:
        print(f"error: a file could not be read or written ({type(exc).__name__}).", file=sys.stderr)
        return EXIT_USAGE
    if args.format == "json":
        print(json.dumps(summary, indent=2))
    else:
        _print_text(summary)
    return code


if __name__ == "__main__":
    sys.exit(main())
