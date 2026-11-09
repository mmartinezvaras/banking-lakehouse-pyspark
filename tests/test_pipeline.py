"""End to end on a small generated dataset: every raw row is accounted for, MERGE applies the
corrections, re-running is idempotent, and the window rules beat the naive rule."""

import json

import pytest

pytestmark = pytest.mark.spark


@pytest.fixture(scope="module")
def lakehouse(spark, tmp_path_factory):
    from banking_lakehouse.generate_data import generate
    from banking_lakehouse.pipeline import run

    root = tmp_path_factory.mktemp("lake")
    stats = generate(root / "raw", n_customers=300, n_transactions=16_000, seed=11)
    summary = run(root / "raw", root / "lake", root / "export", spark=spark)
    return root, stats, summary


def test_every_raw_row_is_accounted_for(spark, lakehouse):
    root, stats, summary = lakehouse
    b1, b2 = summary["batches"]
    assert b1["bronze_rows"] == stats["raw_rows_batch_1"]
    assert b2["bronze_rows"] == stats["raw_rows_batch_2"]
    assert b1["inserted"] + b1["quarantined"] == b1["bronze_rows"]
    # The increment: new rows inserted, corrections updated, the rest quarantined or unchanged re-sends.
    assert b2["updated"] > 0 and b2["inserted"] > 0
    assert b2["inserted"] + b2["updated"] + b2["quarantined"] <= b2["bronze_rows"]


def test_rerun_is_idempotent(spark, lakehouse):
    from banking_lakehouse.pipeline import run

    root, _, _ = lakehouse
    silver_before = spark.read.format("delta").load(str(root / "lake" / "silver" / "transactions")).count()
    again = run(root / "raw", root / "lake", None, spark=spark)
    assert again["batches"] == []
    assert spark.read.format("delta").load(str(root / "lake" / "silver" / "transactions")).count() == silver_before


def test_window_rules_beat_the_naive_rule(lakehouse):
    _, _, summary = lakehouse
    m = {r["rule"]: r for r in summary["rule_metrics"]}
    assert m["window"]["f1"] > m["naive"]["f1"]
    assert m["window"]["share_stopped"] > m["naive"]["share_stopped"]
    assert m["window_review"]["recall"] >= m["window"]["recall"]


def test_dashboard_export(lakehouse):
    root, _, _ = lakehouse
    export = root / "export"
    summary = json.loads((export / "summary.json").read_text())
    assert summary["layers"]["silver_partitions"] == 7  # Jan – Jul 2026
    assert summary["delta"]["time_travel"]["corrected_rows"] > 0
    ops = [h["operation"] for h in summary["delta"]["silver_history"]]
    assert ops[0] == "WRITE" and "MERGE" in ops
    # OPTIMIZE only commits a version when there were small files to compact.
    compacted = summary["delta"]["optimize"]["silver_transactions"]["files_removed"] > 0
    assert ("OPTIMIZE" in ops) == compacted
    for name in ["daily.csv", "burst_example.csv", "trip_example.csv", "recent_alerts.csv"]:
        assert (export / name).stat().st_size > 0, name
