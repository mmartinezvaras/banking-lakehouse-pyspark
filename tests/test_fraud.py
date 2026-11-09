"""Window features and rules on a hand-made timeline: a card-testing attack and a traveller."""

from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.spark

T0 = datetime(2026, 5, 10, 21, 0, 0)


def silver(spark, rows):
    from pyspark.sql import functions as F

    cols = ["tx_id", "customer_id", "ts", "tx_type", "channel", "amount", "country", "fraud_label"]
    df = spark.createDataFrame(rows, cols)
    return (
        df.withColumn("amount", F.col("amount").cast("decimal(12,2)"))
        .withColumn("tx_date", F.to_date("ts"))
        .withColumn("is_foreign", F.col("country") != "ES")
    )


def attack_and_trip(spark):
    at = lambda minutes: T0 + timedelta(minutes=minutes)  # noqa: E731
    rows = [
        # Customer 1: normal week, then a compromised card at 21:00.
        (1, 1, at(-3 * 24 * 60), "card_payment", "pos", 35.0, "ES", 0),
        (2, 1, at(-2 * 24 * 60), "card_payment", "pos", 42.0, "ES", 0),
        (3, 1, at(0), "card_payment", "online", 1.50, "US", 1),  # probe
        (4, 1, at(2), "card_payment", "online", 640.00, "US", 1),  # under €900
        (5, 1, at(4), "card_payment", "online", 720.00, "CN", 1),
        (6, 1, at(5), "card_payment", "online", 1800.00, "CN", 1),
        # Customer 2: a traveller paying a hotel in Lisbon.
        (7, 2, at(-60), "card_payment", "pos", 25.0, "PT", 0),
        (8, 2, at(0), "card_payment", "pos", 1200.0, "PT", 0),
    ]
    from banking_lakehouse.fraud import add_features, apply_rules

    return {r["tx_id"]: r for r in apply_rules(add_features(silver(spark, rows))).collect()}


def test_window_features(spark):
    tx = attack_and_trip(spark)
    assert tx[3]["is_probe"] and not tx[3]["probe_before_10m"]
    assert tx[4]["probe_before_10m"] and tx[4]["tx_count_10m"] == 2
    assert tx[6]["tx_count_10m"] == 4 and tx[6]["countries_10m"] == 2
    assert tx[4]["secs_since_prev"] == 120 and tx[4]["prev_country"] == "US"
    assert tx[3]["secs_to_next"] == 120 and tx[3]["next_amount"] == 640.0
    assert tx[3]["avg_amount_30d"] == pytest.approx(38.5)
    assert tx[6]["day_running_total"] == pytest.approx(1.5 + 640 + 720 + 1800)
    assert tx[1]["secs_since_prev"] is None  # first transaction of the customer


def test_rules_catch_the_attack_but_not_the_traveller(spark):
    tx = attack_and_trip(spark)
    # The naive rule misses the payments under €900 and flags the hotel.
    assert sorted(i for i in tx if tx[i]["rule_naive"]) == [6, 8]
    # Card testing fires on the first big payment; velocity from the third payment on.
    assert tx[4]["rule_card_testing"] and tx[5]["rule_velocity"] and tx[6]["rule_velocity"]
    assert sorted(i for i in tx if tx[i]["rule_window"]) == [4, 5, 6]
    assert "Prueba de tarjeta" in tx[4]["alert_reasons"]
    # The probe itself is only caught by the next-day review rule (it needs lead()).
    assert tx[3]["rule_probe_attack"] and not tx[3]["rule_window"]


def test_evaluation_counts_money_stopped(spark):
    from banking_lakehouse.fraud import add_features, apply_rules, evaluate

    at = lambda minutes: T0 + timedelta(minutes=minutes)  # noqa: E731
    rows = [
        (1, 1, at(0), "card_payment", "online", 2.0, "US", 1),
        (2, 1, at(2), "card_payment", "online", 500.0, "US", 1),
        (3, 1, at(4), "card_payment", "online", 500.0, "US", 1),
        (4, 2, at(0), "card_payment", "pos", 1000.0, "PT", 0),
    ]
    metrics = {m["rule"]: m for m in evaluate(apply_rules(add_features(silver(spark, rows))))}
    window = metrics["window"]
    assert (window["true_positives"], window["false_positives"], window["false_negatives"]) == (2, 0, 1)
    assert window["bursts"] == 1 and window["bursts_detected"] == 1
    assert window["share_stopped"] == pytest.approx(1000 / 1002, abs=0.001)
    assert window["median_payment_of_first_alert"] == 2
    naive = metrics["naive"]
    assert (naive["true_positives"], naive["false_positives"]) == (0, 1) and naive["share_stopped"] == 0
