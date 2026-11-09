"""Silver cleaning: parsing, rejection reasons and duplicate handling, on hand-made rows."""

from datetime import datetime

import pytest

pytestmark = pytest.mark.spark

COLUMNS = ["tx_id", "customer_id", "timestamp", "tx_type", "channel", "amount", "country", "fraud_label"]


def bronze(spark, rows):
    from pyspark.sql import functions as F

    df = spark.createDataFrame(rows, COLUMNS)
    return (
        df.withColumn("_source_file", F.lit("batch.csv"))
        .withColumn("_batch_id", F.lit("b1"))
        .withColumn("_ingested_at", F.current_timestamp())
    )


def customers(spark, ids=(1, 2)):
    return spark.createDataFrame([(i,) for i in ids], ["customer_id"])


def test_fixable_values_are_parsed(spark):
    from banking_lakehouse.silver import clean_transactions

    rows = [
        ("1", "1", "2026-03-01T10:00:00", "card_payment", "pos", "12.50", "ES", "0"),
        ("2", "1", "01/03/2026 11:30:00", " CARD_PAYMENT ", "online", "1.234,56", "fr", "0"),
        ("3", "2", "2026-03-02T09:00:00", "transfer", "app", "€ 42,10", "ES", "1"),
    ]
    silver, quarantine = clean_transactions(bronze(spark, rows), customers(spark))
    got = {r["tx_id"]: r for r in silver.collect()}
    assert quarantine.count() == 0
    assert float(got[1]["amount"]) == 12.50
    assert float(got[2]["amount"]) == 1234.56
    assert float(got[3]["amount"]) == 42.10
    assert got[2]["ts"] == datetime(2026, 3, 1, 11, 30)
    assert got[2]["tx_type"] == "card_payment" and got[2]["country"] == "FR" and got[2]["is_foreign"]
    assert got[3]["fraud_label"] == 1 and got[1]["tx_month"] == "2026-03"


def test_impossible_rows_are_quarantined_with_a_reason(spark):
    from banking_lakehouse.silver import clean_transactions

    rows = [
        ("10", "1", "2026-03-01T10:00:00", "card_payment", "pos", "", "ES", "0"),
        ("11", "1", "2026-03-01T10:00:00", "card_payment", "pos", "-5.00", "ES", "0"),
        ("12", "1", "not-a-date", "card_payment", "pos", "5.00", "ES", "0"),
        ("13", "99", "2026-03-01T10:00:00", "card_payment", "pos", "5.00", "ES", "0"),
        ("14", "1", "2026-03-01T10:00:00", "teleport", "pos", "5.00", "ES", "0"),
        ("15", "1", "2026-03-01T10:00:00", "card_payment", "pos", "5.00", "ES", "0"),
    ]
    silver, quarantine = clean_transactions(bronze(spark, rows), customers(spark))
    reasons = {r["tx_id"]: r["reason"] for r in quarantine.collect()}
    assert reasons == {
        "10": "missing_or_unparseable_amount",
        "11": "non_positive_amount",
        "12": "unparseable_timestamp",
        "13": "unknown_customer",
        "14": "invalid_tx_type",
    }
    assert [r["tx_id"] for r in silver.collect()] == [15]


def test_redelivered_rows_are_kept_once_and_counted(spark):
    from banking_lakehouse.silver import clean_transactions

    row = ("20", "1", "2026-03-01T10:00:00", "card_payment", "pos", "5.00", "ES", "0")
    silver, quarantine = clean_transactions(bronze(spark, [row, row, row]), customers(spark))
    assert silver.count() == 1
    assert [r["reason"] for r in quarantine.collect()] == ["duplicate_delivery", "duplicate_delivery"]


def test_merge_updates_corrections_and_inserts_new_rows(spark, tmp_path):
    from banking_lakehouse.silver import clean_transactions, upsert_transactions

    path = tmp_path / "silver"
    first = [
        ("1", "1", "2026-03-01T10:00:00", "card_payment", "pos", "10.00", "ES", "0"),
        ("2", "1", "2026-03-01T11:00:00", "card_payment", "pos", "20.00", "ES", "0"),
    ]
    second = [
        ("2", "1", "2026-03-01T11:00:00", "card_payment", "pos", "18.00", "ES", "0"),  # correction
        ("1", "1", "2026-03-01T10:00:00", "card_payment", "pos", "10.00", "ES", "0"),  # unchanged re-send
        ("3", "2", "2026-07-01T09:00:00", "transfer", "app", "300.00", "ES", "0"),  # new
    ]
    s1, _ = clean_transactions(bronze(spark, first), customers(spark))
    assert upsert_transactions(spark, s1, path) == {"inserted": 2, "updated": 0}
    s2, _ = clean_transactions(bronze(spark, second), customers(spark))
    assert upsert_transactions(spark, s2, path) == {"inserted": 1, "updated": 1}

    table = spark.read.format("delta").load(str(path))
    amounts = {r["tx_id"]: float(r["amount"]) for r in table.collect()}
    assert amounts == {1: 10.0, 2: 18.0, 3: 300.0}
    # Time travel: version 0 still has the original amount.
    v0 = spark.read.format("delta").option("versionAsOf", 0).load(str(path))
    assert float(v0.where("tx_id = 2").first()["amount"]) == 20.0
