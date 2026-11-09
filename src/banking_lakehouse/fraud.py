"""Fraud features with window functions, detection rules, and their evaluation.

Every feature is computed over each customer's own transactions in time order:

    by_customer = partition by customer_id, order by time
    last_10m    = the same window, limited to the 10 minutes up to the current payment

=====================  ========================================================  ================
feature                meaning                                                    window
=====================  ========================================================  ================
tx_count_10m           payments in the last 10 minutes (velocity)                 count / range
amount_10m             money spent in the last 10 minutes                         sum / range
countries_10m          different countries in the last 10 minutes                 collect_set
probe_before_10m       a tiny (< €5) online payment abroad in the 10 min before   max / range
secs_since_prev        time since the previous transaction                        lag
prev_country           country of the previous transaction                        lag
secs_to_next           time until the next transaction                            lead
next_amount            amount of the next transaction                             lead
avg_amount_30d         the customer's average amount over the previous 30 days     avg / range
amount_vs_30d          this amount ÷ that average (a sudden jump)                 —
day_running_total      money spent so far that day                                running sum
=====================  ========================================================  ================

The rules use only past data (lag, ranges ending at the current row), so they could run on a
live stream. The one exception, "probe → attack", uses lead() and is for investigating the day
after: it marks the tiny probe payments once the attack that followed is known.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from functools import reduce

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql import functions as F

TINY = 5.0  # € — card-testing probes
TEN_MIN = 600
DAY = 86_400


def add_features(silver: DataFrame) -> DataFrame:
    df = silver.withColumn("ts_s", F.col("ts").cast("long")).withColumn("amount_d", F.col("amount").cast("double"))
    by_customer = Window.partitionBy("customer_id").orderBy("ts_s", "tx_id")
    by_time = Window.partitionBy("customer_id").orderBy("ts_s")
    last_10m = by_time.rangeBetween(-TEN_MIN, 0)
    before_10m = by_time.rangeBetween(-TEN_MIN, -1)
    previous_30d = by_time.rangeBetween(-30 * DAY, -1)
    so_far_today = (
        Window.partitionBy("customer_id", "tx_date")
        .orderBy("ts_s", "tx_id")
        .rowsBetween(Window.unboundedPreceding, Window.currentRow)
    )
    is_probe = (F.col("amount_d") < TINY) & (F.col("channel") == "online") & F.col("is_foreign")

    return (
        df.withColumn("tx_count_10m", F.count(F.lit(1)).over(last_10m))
        .withColumn("amount_10m", F.round(F.sum("amount_d").over(last_10m), 2))
        .withColumn("countries_10m", F.size(F.collect_set("country").over(last_10m)))
        .withColumn("probe_before_10m", F.coalesce(F.max(is_probe.cast("int")).over(before_10m), F.lit(0)) == 1)
        .withColumn("secs_since_prev", F.col("ts_s") - F.lag("ts_s").over(by_customer))
        .withColumn("prev_country", F.lag("country").over(by_customer))
        .withColumn("secs_to_next", F.lead("ts_s").over(by_customer) - F.col("ts_s"))
        .withColumn("next_amount", F.lead("amount_d").over(by_customer))
        .withColumn("avg_amount_30d", F.round(F.avg("amount_d").over(previous_30d), 2))
        .withColumn("amount_vs_30d", F.round(F.col("amount_d") / F.col("avg_amount_30d"), 2))
        .withColumn("day_running_total", F.round(F.sum("amount_d").over(so_far_today), 2))
        .withColumn("is_probe", is_probe)
    )


# ------------------------------------------------------------------------------------------
# Rules
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    key: str
    name: str
    description: str
    realtime: bool


def _card_abroad() -> Column:
    return (F.col("tx_type") == "card_payment") & F.col("is_foreign")


RULES: dict[str, tuple[Rule, Column]] = {}


def _rule(key: str, name: str, description: str, condition: Column, realtime: bool = True) -> None:
    RULES[key] = (Rule(key, name, description, realtime), condition)


def _define_rules() -> None:
    hop = (
        F.col("prev_country").isNotNull()
        & (F.col("prev_country") != F.col("country"))
        & (F.col("prev_country") != "ES")
        & (F.col("secs_since_prev") <= 3600)
    )
    _rule(
        "naive",
        "Pago grande en el extranjero",
        "card payment abroad over €900: the rule without window functions",
        _card_abroad() & (F.col("amount_d") > 900),
    )
    _rule(
        "velocity",
        "Velocidad",
        "3 or more online card payments abroad within 10 minutes",
        _card_abroad() & (F.col("channel") == "online") & (F.col("tx_count_10m") >= 3),
    )
    _rule(
        "card_testing",
        "Prueba de tarjeta",
        "a payment of €100+ abroad within 10 minutes of a tiny online probe",
        _card_abroad() & F.col("probe_before_10m") & (F.col("amount_d") >= 100),
    )
    _rule(
        "country_hop",
        "Salto de país",
        "a payment in a different foreign country less than an hour after the previous one, 5× the usual amount",
        _card_abroad() & hop & (F.col("amount_vs_30d") >= 5),
    )
    _rule(
        "probe_attack",
        "Sonda antes del ataque (revisión)",
        "a tiny probe followed within 10 minutes by a payment of €100+ (uses lead: next-day review)",
        F.col("is_probe") & (F.col("secs_to_next") <= TEN_MIN) & (F.col("next_amount") >= 100),
        realtime=False,
    )


_define_rules()
WINDOW_RULES = ["velocity", "card_testing", "country_hop"]  # the real-time combination


def apply_rules(features: DataFrame) -> DataFrame:
    """One boolean column per rule (rule_<key>), the real-time combination (rule_window) and,
    for alerts, the list of rules that fired."""
    df = features
    for key, (_, condition) in RULES.items():
        df = df.withColumn(f"rule_{key}", F.coalesce(condition, F.lit(False)))
    df = df.withColumn("rule_window", reduce(operator.or_, [F.col(f"rule_{k}") for k in WINDOW_RULES]))
    df = df.withColumn("rule_window_review", F.col("rule_window") | F.col("rule_probe_attack"))
    reasons = [F.when(F.col(f"rule_{k}"), F.lit(RULES[k][0].name)) for k in WINDOW_RULES]
    return df.withColumn("alert_reasons", F.array_compact(F.array(*reasons)))


# ------------------------------------------------------------------------------------------
# Evaluation against the ground truth
# ------------------------------------------------------------------------------------------

EVALUATED = {
    "naive": "Pago grande en el extranjero (sin ventanas)",
    "window": "Reglas con ventanas (tiempo real)",
    "window_review": "Ventanas + revisión con lead",
}


def label_bursts(scored: DataFrame) -> DataFrame:
    """Give each fraud burst an ID: fraud payments of the same customer less than 30 minutes apart."""
    fraud = scored.where(F.col("fraud_label") == 1)
    w = Window.partitionBy("customer_id").orderBy("ts_s", "tx_id")
    gap = F.col("ts_s") - F.lag("ts_s").over(w)
    starts = F.when(gap.isNull() | (gap > 1800), 1).otherwise(0)
    return fraud.withColumn("_start", starts).withColumn(
        "burst_id", F.concat_ws("-", F.col("customer_id"), F.sum("_start").over(w.rowsBetween(Window.unboundedPreceding, 0)))
    )


def evaluate(scored: DataFrame) -> list[dict]:
    """Per rule: precision, recall, F1, false alerts per day, and, per fraud burst, how much of
    the stolen money would have been stopped if the card were blocked at the first alert."""
    days = scored.select(F.countDistinct("tx_date")).first()[0] or 1
    bursts = label_bursts(scored).select("burst_id", "ts_s", "amount_d", *[f"rule_{k}" for k in EVALUATED]).collect()
    results = []
    for key, name in EVALUATED.items():
        flag = F.col(f"rule_{key}")
        counts = scored.agg(
            F.sum((flag & (F.col("fraud_label") == 1)).cast("int")).alias("tp"),
            F.sum((flag & (F.col("fraud_label") == 0)).cast("int")).alias("fp"),
            F.sum((~flag & (F.col("fraud_label") == 1)).cast("int")).alias("fn"),
        ).first()
        tp, fp, fn = (counts["tp"] or 0), (counts["fp"] or 0), (counts["fn"] or 0)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

        per_burst: dict[str, list] = {}
        for row in bursts:
            per_burst.setdefault(row["burst_id"], []).append(row)
        detected, stolen, stopped, first_hit = 0, 0.0, 0.0, []
        for rows in per_burst.values():
            rows.sort(key=lambda r: r["ts_s"])
            stolen += sum(r["amount_d"] for r in rows)
            hits = [i for i, r in enumerate(rows) if r[f"rule_{key}"]]
            if hits:
                detected += 1
                first_hit.append(hits[0] + 1)
                # Blocking the card at the first alert declines that payment and every later one.
                stopped += sum(r["amount_d"] for r in rows[hits[0] :])
        results.append(
            {
                "rule": key,
                "name": name,
                "true_positives": tp,
                "false_positives": fp,
                "false_negatives": fn,
                "precision": round(precision, 3),
                "recall": round(recall, 3),
                "f1": round(f1, 3),
                "false_alerts_per_day": round(fp / days, 2),
                "bursts": len(per_burst),
                "bursts_detected": detected,
                "fraud_amount": round(stolen, 2),
                "fraud_amount_stopped": round(stopped, 2),
                "share_stopped": round(stopped / stolen, 3) if stolen else 0.0,
                "median_payment_of_first_alert": sorted(first_hit)[len(first_hit) // 2] if first_hit else None,
            }
        )
    return results
