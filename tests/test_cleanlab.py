"""Optional Cleanlab integration: works when installed, degrades honestly when not, never required."""

import sys
from pathlib import Path

import numpy as np
import pytest

from app.config import Limits
from app.services import label_review
from tests.conftest import load, rows_csv, upload
from tests.test_api import SECRET

ROOT = Path(__file__).resolve().parent.parent
LIMITS = Limits(max_label_review_rows=5000)


def noisy_dataset(n: int = 300, flipped: int = 12, seed: int = 3) -> tuple[str, list[int]]:
    """Two well-separated classes with `flipped` labels deliberately wrong."""
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 2, n)
    x1 = y * 3.0 + rng.normal(0, 0.6, n)
    x2 = y * -2.0 + rng.normal(0, 0.6, n)
    wrong = sorted(rng.choice(n, flipped, replace=False).tolist())
    labels = ["pos" if v else "neg" for v in y]
    for i in wrong:
        labels[i] = "neg" if labels[i] == "pos" else "pos"
    rows = [f"{x1[i]:.4f},{x2[i]:.4f},{labels[i]}" for i in range(n)]
    return rows_csv("x1,x2,label", rows), wrong


def review(text: str):
    return label_review.review_labels(load(text), "label", LIMITS)


def without_cleanlab(monkeypatch):
    monkeypatch.setitem(sys.modules, "cleanlab", None)  # makes `import cleanlab` raise ImportError
    monkeypatch.setitem(sys.modules, "cleanlab.filter", None)


# --- Never a hard requirement -------------------------------------------------------------------


def test_cleanlab_is_only_an_optional_requirement():
    required = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    optional = (ROOT / "requirements-optional.txt").read_text(encoding="utf-8").lower()
    assert "cleanlab" not in required
    assert "cleanlab==2.9.0" in optional


def test_app_code_never_imports_cleanlab_at_module_level():
    for path in (ROOT / "app").rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(("import cleanlab", "from cleanlab")):
                pytest.fail(f"{path.name} imports cleanlab at module level")


def test_missing_extra_is_reported_and_label_review_still_works(monkeypatch):
    without_cleanlab(monkeypatch)
    text, _ = noisy_dataset()
    result = review(text)
    assert result.status == "completed"
    assert result.cleanlab.status == "unavailable"
    assert "requirements-optional.txt" in result.cleanlab.reason
    assert all(c.cleanlab_flagged is None for c in result.candidates)


def test_core_label_review_is_identical_with_or_without_the_extra(monkeypatch):
    text, _ = noisy_dataset()
    pytest.importorskip("cleanlab")
    with_extra = review(text)
    without_cleanlab(monkeypatch)
    without = review(text)
    strip = lambda r: r.model_dump(exclude={"cleanlab", "candidates"}) | {
        "candidates": [c.model_dump(exclude={"cleanlab_flagged"}) for c in r.candidates]}
    assert strip(with_extra) == strip(without)


def test_a_failing_library_never_breaks_label_review(monkeypatch):
    cleanlab_filter = pytest.importorskip("cleanlab.filter")

    def broken(**kwargs):
        raise RuntimeError("internal detail " + SECRET)

    monkeypatch.setattr(cleanlab_filter, "find_label_issues", broken)
    result = review(noisy_dataset()[0])
    assert result.status == "completed" and result.cleanlab.status == "failed"
    assert "RuntimeError" in result.cleanlab.reason and SECRET not in result.model_dump_json()


# --- With the extra installed -------------------------------------------------------------------


def test_cleanlab_finds_most_planted_label_errors():
    pytest.importorskip("cleanlab")
    text, wrong = noisy_dataset()
    result = review(text)
    c = result.cleanlab
    assert c.status == "computed" and c.version == "2.9.0"
    found = set(c.issue_row_indices) & set(wrong)
    assert len(found) >= len(wrong) // 2
    assert c.n_issues >= len(found)


def test_flags_counts_and_ordering_are_consistent():
    pytest.importorskip("cleanlab")
    result = review(noisy_dataset()[0])
    c = result.cleanlab
    assert c.n_issues_among_candidates == sum(1 for x in result.candidates if x.cleanlab_flagged)
    assert all(x.cleanlab_flagged is not None for x in result.candidates)
    assert len(c.issue_row_indices) == min(c.n_issues, label_review.CANDIDATES_LIMIT)
    assert len(set(c.issue_row_indices)) == len(c.issue_row_indices)


def test_cleanlab_results_are_deterministic():
    pytest.importorskip("cleanlab")
    text, _ = noisy_dataset()
    assert review(text).model_dump_json() == review(text).model_dump_json()


def test_label_review_endpoint_includes_the_cleanlab_summary(client):
    body = upload(client, "/api/label-review", noisy_dataset()[0], target_column="label").json()
    assert body["cleanlab"]["status"] in ("computed", "unavailable")
