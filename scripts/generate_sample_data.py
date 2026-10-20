"""Generate the synthetic demo datasets in sample_data/ (deterministic; no real people or data).

Run from the repository root:  python scripts/generate_sample_data.py

Each file contains deliberately planted defects, listed in sample_data/README.md.
"""

import csv
from datetime import date, timedelta
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent.parent / "sample_data"
PLANS = ["Basic", "Standard", "Premium"]
REGIONS = ["North", "South", "East", "West"]


def _write(name: str, header: list[str], rows: list[list[object]]) -> None:
    with open(OUT / name, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _customer(rng: np.random.Generator, i: int) -> tuple[list[object], float]:
    tenure = int(rng.integers(1, 72))
    tickets = int(rng.poisson(1.5))
    plan = PLANS[int(rng.integers(0, 3))]
    spend = round(float(rng.lognormal(3.6, 0.35)) * (1 + PLANS.index(plan) * 0.4), 2)
    age = int(rng.integers(18, 75))
    risk = -1.0 + 1.1 * tickets - 0.09 * tenure + (1.2 if plan == "Basic" else 0.0)
    churn_prob = 1 / (1 + np.exp(-risk))
    signup = date(2021, 1, 1) + timedelta(days=int(rng.integers(0, 1000)))
    row = [
        f"C{i:05d}",
        signup.isoformat(),
        age,
        spend,
        plan,
        REGIONS[int(rng.integers(0, 4))],
        "US",
        "",
        tickets,
        tenure,
        tenure * 30,
    ]
    return row, float(churn_prob)


def churn(rng: np.random.Generator) -> tuple[list[str], list[list[object]]]:
    header = [
        "customer_id", "signup_date", "age", "monthly_spend", "plan", "region", "country",
        "legacy_segment", "support_tickets", "tenure_months", "tenure_days", "cancellation_code",
        "churned",
    ]
    rows = []
    for i in range(1, 521):
        row, prob = _customer(rng, i)
        churned = "yes" if rng.random() < prob else "no"
        # Leakage: a code only recorded after a customer has already cancelled.
        row.append(f"X{int(rng.integers(1, 4))}" if churned == "yes" else "NONE")
        row.append(churned)
        rows.append(row)
    for idx in rng.choice(len(rows), 30, replace=False):  # ~6% missing ages
        rows[idx][2] = ""
    for idx in rng.choice(len(rows), 3, replace=False):  # implausible ages: outlier candidates
        rows[idx][2] = int(rng.choice([142, 151, 160]))
    for idx in rng.choice(len(rows), 12, replace=False):  # inconsistent category spellings
        rows[idx][4] = {"Basic": "basic ", "Standard": "STANDARD", "Premium": "premium"}[rows[idx][4]]
    for idx in rng.choice(len(rows), 6, replace=False):  # unlabeled rows
        rows[idx][-1] = ""
    for idx in rng.choice(len(rows), 8, replace=False):  # label noise for label review
        if rows[idx][-1]:
            rows[idx][-1] = "no" if rows[idx][-1] == "yes" else "yes"
    duplicates = [list(rows[int(i)]) for i in rng.choice(len(rows), 15, replace=False)]
    return header, rows + duplicates


def churn_holdout(
    rng: np.random.Generator, train_rows: list[list[object]]
) -> list[list[object]]:
    rows = []
    for i in range(10001, 10161):
        row, prob = _customer(rng, i)
        churned = "yes" if rng.random() < prob else "no"
        row += [f"X{int(rng.integers(1, 4))}" if churned == "yes" else "NONE", churned]
        rows.append(row)
    leaked = [list(train_rows[int(i)]) for i in rng.choice(len(train_rows), 20, replace=False)]
    return rows + leaked


def sensors(rng: np.random.Generator) -> tuple[list[str], list[list[object]]]:
    header = [
        "reading_id", "timestamp", "temperature_c", "humidity_pct", "pressure_hpa",
        "voltage_reading", "firmware", "site", "energy_kwh",
    ]
    rows = []
    start = date(2024, 3, 1)
    for i in range(300):
        temp = round(float(rng.normal(21, 4)), 2)
        humidity = round(float(rng.uniform(30, 70)), 1)
        pressure = round(float(rng.normal(1013, 6)), 1)
        voltage = round(float(rng.normal(230, 3)), 1)
        energy = round(2 + 0.35 * temp + 0.02 * humidity + float(rng.normal(0, 0.8)), 3)
        ts = f"{(start + timedelta(days=i // 24)).isoformat()}T{i % 24:02d}:00:00"
        rows.append([i + 1, ts, temp, humidity, pressure, voltage, "v2.4.1",
                     ["plant-a", "plant-b"][i % 2], energy])
    for idx in rng.choice(len(rows), 9, replace=False):  # sensor glitches stored as text
        rows[idx][5] = str(rng.choice(["ERR", "n/a?", "--"]))
    for idx in rng.choice(len(rows), 2, replace=False):  # division-by-zero artefacts
        rows[idx][3] = "inf"
    for idx in rng.choice(len(rows), 45, replace=False):  # 15% missing pressure
        rows[idx][4] = ""
    return header, rows


def main() -> None:
    rng = np.random.default_rng(42)
    header, churn_rows = churn(rng)
    _write("customer_churn.csv", header, churn_rows)
    _write("customer_churn_holdout.csv", header, churn_holdout(rng, churn_rows))
    header, sensor_rows = sensors(rng)
    _write("sensor_energy.csv", header, sensor_rows)


if __name__ == "__main__":
    main()
