"""Split Doctor: split advice for one file, entity and time checks across two files."""

from pathlib import Path

import pytest

from app.services import leakage, splits
from app.services.loader import DatasetError, load_csv
from tests.conftest import TEST_LIMITS, load, rows_csv, upload
from tests.test_api import SECRET, assert_safe_error

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"


def advise(text: str, target=None, entity=None, time=None):
    return splits.split_advice(load(text), target, entity, time)


def dated(n: int, start_day: int = 1, label=lambda i: "yn"[i % 2]) -> str:
    rows = [f"{i},2024-{1 + (start_day + i) // 28:02d}-{1 + (start_day + i) % 28:02d},{label(i)}" for i in range(n)]
    return rows_csv("id,day,label", rows)


# --- Strategy selection -------------------------------------------------------------------------


def test_no_columns_means_random_with_an_explanation():
    advice = advise(rows_csv("a,b", [f"{i},{i * 2}" for i in range(30)]))
    assert advice.recommended == "random"
    assert advice.task is None and advice.entity is None and advice.time is None
    assert "random split" in advice.reasons[0]


def test_classification_target_means_stratified():
    advice = advise(rows_csv("x,y", [f"{i},{'a' if i % 10 else 'b'}" for i in range(50)]), target="y")
    assert advice.task == "classification"
    assert advice.recommended == "stratified"
    assert any("smallest is 10.0%" in r for r in advice.reasons)


def test_regression_target_means_random():
    advice = advise(rows_csv("x,y", [f"{i},{i * 1.37}" for i in range(50)]), target="y")
    assert advice.task == "regression" and advice.recommended == "random"


def test_single_class_and_singleton_class_cannot_be_stratified():
    single = advise(rows_csv("x,y", [f"{i},a" for i in range(30)]), target="y")
    assert single.recommended == "random" and any("single class" in r for r in single.reasons)
    singleton = advise(rows_csv("x,y", [f"{i},{'b' if i == 0 else 'a'}" for i in range(30)]), target="y")
    assert singleton.recommended == "random" and any("at least two" in r for r in singleton.reasons)


def test_repeated_entities_mean_group_split_and_the_estimate_is_exact():
    # 25 entities with 2 rows each: under a 20% holdout a test row's sibling is in training with
    # probability 0.8, so the expected share is exactly 0.8.
    text = rows_csv("cust,v", [f"c{i // 2},{i}" for i in range(50)])
    advice = advise(text, entity="cust")
    assert advice.recommended == "group"
    e = advice.entity
    assert (e.n_entities, e.n_entities_with_repeats, e.max_rows_per_entity) == (25, 25, 2)
    assert e.rows_in_repeated_entities_fraction == 1.0
    assert e.expected_test_rows_with_seen_entity_fraction == 0.8


def test_repeated_entities_with_a_class_target_mean_stratified_group():
    text = rows_csv("cust,y", [f"c{i // 2},{'yn'[i % 3 == 0]}" for i in range(60)])
    assert advise(text, target="y", entity="cust").recommended == "stratified_group"


def test_unique_entities_do_not_need_grouping():
    advice = advise(rows_csv("cust,v", [f"c{i},{i}" for i in range(40)]), entity="cust")
    assert advice.recommended == "random"
    assert advice.entity.n_entities_with_repeats == 0
    assert advice.entity.expected_test_rows_with_seen_entity_fraction == 0.0
    assert any("not needed" in r for r in advice.reasons)


def test_grouping_threshold_is_inclusive():
    # 2 of 40 rows (5.0%) share an entity: exactly at GROUP_MIN_REPEATED_FRACTION.
    rows = [f"c{i},{i}" for i in range(38)] + ["dup,1", "dup,2"]
    assert splits.GROUP_MIN_REPEATED_FRACTION == 0.05
    assert advise(rows_csv("cust,v", rows), entity="cust").recommended == "group"


def test_too_few_entities_do_not_get_a_group_split():
    advice = advise(rows_csv("site,v", [f"s{i % 3},{i}" for i in range(60)]), entity="site")
    assert advice.recommended == "random"
    assert any("too few" in r for r in advice.reasons)


def test_missing_entity_values_are_counted_not_grouped():
    rows = [f"c{i // 2},{i}" for i in range(40)] + [f",{i}" for i in range(10)]
    e = advise(rows_csv("cust,v", rows), entity="cust").entity
    assert e.n_rows_missing_entity == 10 and e.n_entities == 20


def test_usable_time_column_means_time_split_with_cutoff():
    advice = advise(dated(50), time="day")
    t = advice.time
    assert advice.recommended == "time" and t.usable
    assert (t.n_parsed, t.n_unparseable, t.n_missing) == (50, 0, 0)
    assert t.rows_in_time_order is True
    assert t.holdout_cutoff.startswith("2024-02-") and t.min < t.holdout_cutoff <= t.max


def test_time_beats_entities_but_mentions_them():
    rows = [f"c{i // 2},2024-01-{1 + i % 28:02d}" for i in range(56)]
    advice = advise(rows_csv("cust,day", rows), entity="cust", time="day")
    assert advice.recommended == "time"
    assert any("Entities also repeat" in r for r in advice.reasons)


def test_unparseable_time_column_falls_back_with_a_reason():
    rows = [f"{i},{'2024-01-05' if i < 5 else 'soon'}" for i in range(40)]
    advice = advise(rows_csv("id,when", rows), time="when")
    assert advice.recommended == "random" and not advice.time.usable
    assert advice.time.n_unparseable == 35
    assert any("could not be used" in r for r in advice.reasons)


def test_time_needs_two_distinct_dates_and_enough_rows():
    same_day = advise(rows_csv("id,d", [f"{i},2024-01-01" for i in range(30)]), time="d")
    assert not same_day.time.usable
    few = advise(rows_csv("id,d", [f"{i},2024-01-{i + 1:02d}" for i in range(splits.TIME_MIN_ROWS - 1)]), time="d")
    assert not few.time.usable


def test_out_of_order_rows_are_reported():
    rows = [f"{i},2024-01-{28 - i:02d}" for i in range(20)]
    assert advise(rows_csv("id,d", rows), time="d").time.rows_in_time_order is False


def test_class_shift_over_time_is_measured():
    shifted = advise(dated(100, label=lambda i: "y" if i >= 80 else "n"), target="label", time="day")
    assert shifted.time.target_shift_measure == "total_variation_distance"
    assert shifted.time.target_shift == 1.0
    assert any("differs from earlier rows" in r for r in shifted.reasons)
    stable = advise(dated(100), target="label", time="day")
    assert stable.time.target_shift < splits.TVD_SHIFT_THRESHOLD
    assert any("is similar" in r for r in stable.reasons)


def test_regression_shift_uses_standardized_mean_difference():
    rows = [f"2024-{1 + i // 28:02d}-{1 + i % 28:02d},{(i % 5) + (10 if i >= 80 else 0)}.5" for i in range(100)]
    advice = advise(rows_csv("day,y", rows), target="y", time="day")
    assert advice.time.target_shift_measure == "standardized_mean_difference"
    assert advice.time.target_shift > splits.SMD_SHIFT_THRESHOLD


def test_shift_is_skipped_when_the_holdout_is_too_small():
    advice = advise(dated(40), target="label", time="day")
    assert advice.time.usable and advice.time.target_shift is None


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"target": "nope"}, "unknown_target_column"),
        ({"entity": "nope"}, "unknown_entity_column"),
        ({"time": "nope"}, "unknown_time_column"),
        ({"target": "a", "entity": "a"}, "invalid_request"),
        ({"entity": "a", "time": "a"}, "invalid_request"),
    ],
)
def test_invalid_column_choices_are_rejected(kwargs, code):
    with pytest.raises(DatasetError) as info:
        advise("a,b\n1,2\n", **kwargs)
    assert info.value.code == code


def test_advice_is_deterministic():
    text = dated(100, label=lambda i: "yn"[i % 3 == 0])
    assert advise(text, "label", "id", "day") == advise(text, "label", "id", "day")


def test_sample_churn_data():
    raw = (SAMPLES / "customer_churn.csv").read_bytes()
    advice = splits.split_advice(load_csv(raw, TEST_LIMITS, "c.csv"), "churned", "customer_id", "signup_date")
    assert advice.recommended == "time" and advice.time.usable
    # The 15 appended duplicate rows make 15 customer ids repeat: 30 of 535 rows (5.6%), just over
    # the grouping threshold, so the advice also mentions keeping entities on one side.
    assert advice.entity.n_entities_with_repeats == 15
    assert advice.entity.rows_in_repeated_entities_fraction == pytest.approx(30 / 535, abs=1e-6)
    assert any("Entities also repeat" in r for r in advice.reasons)


# --- Across two files ---------------------------------------------------------------------------


def overlap(train: str, test: str, **kwargs):
    return leakage.train_test_overlap(load(train), load(test), None, **kwargs)


def test_entity_overlap_counts_rows_and_entities():
    train = rows_csv("cust,v", [f"c{i},{i}" for i in range(20)])
    test = rows_csv("cust,v", ["c1,100", "c1,101", "c2,102", "new,103"])
    result = overlap(train, test, entity_column="cust")
    e = result.entity_overlap
    assert (e.n_test_entities, e.n_shared_entities, e.n_test_rows_with_seen_entity) == (3, 2, 3)
    assert e.test_rows_with_seen_entity_fraction == 0.75
    finding = next(f for f in result.findings if f.code == "train_test_entity_overlap")
    assert finding.kind == "potential_issue" and finding.severity == "medium"
    assert finding.evidence["n_shared_entities"] == 2


def test_entity_values_match_across_numeric_formats():
    result = overlap("id,v\n7,1\n8,2\n", "id,v\n7.0,3\n9.0,4\n", entity_column="id")
    assert result.entity_overlap.n_test_rows_with_seen_entity == 1


def test_small_entity_overlap_is_low_severity_and_none_means_no_finding():
    train = rows_csv("cust,v", [f"c{i},{i}" for i in range(10)])
    test = rows_csv("cust,v", ["c1,0"] + [f"n{i},{i}" for i in range(99)])
    low = overlap(train, test, entity_column="cust")
    assert next(f for f in low.findings if f.code == "train_test_entity_overlap").severity == "low"
    clean = overlap(train, rows_csv("cust,v", ["z,1"]), entity_column="cust")
    assert clean.entity_overlap.n_test_rows_with_seen_entity == 0
    assert all(f.code != "train_test_entity_overlap" for f in clean.findings)


def test_temporal_order_counts_test_rows_before_the_newest_training_row():
    train = "id,d\n1,2024-01-01\n2,2024-03-01\n"
    test = "id,d\n3,2024-02-01\n4,2024-03-01\n5,2024-04-01\n"
    result = overlap(train, test, time_column="d")
    t = result.temporal_order
    assert t.n_test_rows_before_train_max == 1 and t.test_rows_before_train_max_fraction == pytest.approx(1 / 3, abs=1e-6)
    assert t.train_max.startswith("2024-03-01") and t.test_min.startswith("2024-02-01")
    assert any(f.code == "train_test_temporal_overlap" for f in result.findings)


def test_sentences_show_readable_dates_while_fields_keep_full_iso():
    from app.services.profiler import display_time

    assert display_time("2024-03-01T00:00:00+00:00") == "2024-03-01"
    assert display_time("2024-03-01T14:30:05+00:00") == "2024-03-01 14:30:05 UTC"
    result = overlap("id,d\n1,2024-03-01\n", "id,d\n2,2024-02-01\n", time_column="d")
    finding = next(f for f in result.findings if f.code == "train_test_temporal_overlap")
    assert "(2024-03-01)" in finding.explanation
    assert result.temporal_order.train_max == "2024-03-01T00:00:00+00:00"


def test_strictly_later_test_rows_produce_no_temporal_finding():
    result = overlap("id,d\n1,2024-01-01\n", "id,d\n2,2024-01-02\n", time_column="d")
    assert result.temporal_order.n_test_rows_before_train_max == 0
    assert all(f.code != "train_test_temporal_overlap" for f in result.findings)


def test_timezones_are_compared_in_utc():
    # 2024-01-01T23:00-02:00 is 2024-01-02T01:00Z, after the training row.
    result = overlap("id,d\n1,2024-01-02T00:00:00Z\n", "id,d\n2,2024-01-01T23:00:00-02:00\n", time_column="d")
    assert result.temporal_order.n_test_rows_before_train_max == 0


@pytest.mark.parametrize(
    ("train", "test", "kwargs", "code"),
    [
        ("a,d\n1,2024-01-01\n", "a\n1\n", {"time_column": "d"}, "unknown_time_column"),
        ("a,e\n1,x\n", "a\n1\n", {"entity_column": "e"}, "unknown_entity_column"),
        ("a,d\n1,later\n", "a,d\n1,2024-01-01\n", {"time_column": "d"}, "unusable_time_column"),
    ],
)
def test_cross_file_column_errors(train, test, kwargs, code):
    with pytest.raises(DatasetError) as info:
        overlap(train, test, **kwargs)
    assert info.value.code == code


def test_sample_holdout_shares_customers_with_training():
    train = load_csv((SAMPLES / "customer_churn.csv").read_bytes(), TEST_LIMITS, "train.csv")
    test = load_csv((SAMPLES / "customer_churn_holdout.csv").read_bytes(), TEST_LIMITS, "test.csv")
    result = leakage.train_test_overlap(train, test, "churned", "customer_id", "signup_date")
    assert result.entity_overlap.n_test_rows_with_seen_entity == 20  # the 20 copied rows
    assert result.temporal_order.n_test_rows_before_train_max > 0


# --- API ----------------------------------------------------------------------------------------


def test_split_advice_endpoint_with_parsing_options(client):
    text = dated(60).replace(",", ";")
    body = upload(
        client, "/api/split-advice", text, delimiter="semicolon",
        target_column="label", entity_column="id", time_column="day",
    ).json()
    assert body["recommended"] == "time"
    assert body["dataset"]["parsing"]["delimiter"] == "semicolon"
    assert body["entity"]["n_entities"] == 60 and body["time"]["usable"] is True


def test_split_advice_endpoint_without_columns(client):
    body = upload(client, "/api/split-advice", "a,b\n1,2\n").json()
    assert body["recommended"] == "random" and body["limitations"]


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"entity_column": SECRET}, "unknown_entity_column"),
        ({"time_column": SECRET}, "unknown_time_column"),
        ({"entity_column": "a", "time_column": "a"}, "invalid_request"),
    ],
)
def test_split_advice_errors_are_safe(client, fields, code):
    assert_safe_error(upload(client, "/api/split-advice", "a,b\n1,2\n", **fields), 422, code)


def test_overlap_endpoint_accepts_entity_and_time_columns(client):
    train = rows_csv("cust,d", [f"c{i},2024-01-{i + 1:02d}" for i in range(10)])
    test = "cust,d\nc1,2024-01-05\nnew,2024-02-01\n"
    body = client.post(
        "/api/train-test-overlap",
        files={"train_file": ("a.csv", train.encode()), "test_file": ("b.csv", test.encode())},
        data={"entity_column": "cust", "time_column": "d"},
    ).json()
    assert body["entity_overlap"]["n_test_rows_with_seen_entity"] == 1
    assert body["temporal_order"]["n_test_rows_before_train_max"] == 1
    codes = {f["code"] for f in body["findings"]}
    assert {"train_test_entity_overlap", "train_test_temporal_overlap"} <= codes


def test_overlap_endpoint_without_new_fields_is_unchanged(client):
    body = client.post(
        "/api/train-test-overlap",
        files={"train_file": ("a.csv", b"a\n1\n"), "test_file": ("b.csv", b"a\n2\n")},
    ).json()
    assert body["entity_overlap"] is None and body["temporal_order"] is None
