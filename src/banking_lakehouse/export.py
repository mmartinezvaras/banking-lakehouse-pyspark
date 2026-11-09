"""Small, deterministic extracts of the lakehouse for the dashboard (dashboard/data/).

The dashboard never runs Spark: it reads these files, so it can be hosted for free and opens
instantly. They contain no run timestamps, so re-running the pipeline on the same data
produces identical files (CI only commits them when the data or the logic changed).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from banking_lakehouse import fraud

FEATURE_COLUMNS = [
    "tx_id",
    "customer_id",
    "ts",
    "tx_type",
    "channel",
    "amount_d",
    "country",
    "fraud_label",
    "secs_since_prev",
    "tx_count_10m",
    "amount_10m",
    "probe_before_10m",
    "amount_vs_30d",
    "rule_naive",
    "rule_velocity",
    "rule_card_testing",
    "rule_country_hop",
    "rule_probe_attack",
    "rule_window",
]


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        if not rows:
            return
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _rows(df: DataFrame) -> list[dict]:
    out = []
    for row in df.collect():
        d = row.asDict()
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
            elif isinstance(v, bool):
                d[k] = int(v)
            elif isinstance(v, float):
                d[k] = round(v, 2)
        out.append(d)
    return out


def _example_burst(scored: DataFrame) -> DataFrame:
    """The customer's activity around one fraud burst, preferring a burst that the naive rule
    partly misses (amounts under €900) but the window rules catch."""
    bursts = (
        fraud.label_bursts(scored)
        .groupBy("burst_id", "customer_id")
        .agg(
            F.min("ts_s").alias("start"),
            F.max("ts_s").alias("end"),
            F.sum(F.col("rule_naive").cast("int")).alias("naive_hits"),
            F.sum(F.col("rule_window").cast("int")).alias("window_hits"),
            F.count(F.lit(1)).alias("n"),
        )
        .orderBy(F.col("naive_hits").asc(), F.col("window_hits").desc(), F.col("n").desc(), "burst_id")
        .first()
    )
    return scored.where(
        (F.col("customer_id") == bursts["customer_id"])
        & (F.col("ts_s").between(bursts["start"] - 6 * 3600, bursts["end"] + 3 * 3600))
    ).orderBy("ts_s", "tx_id")


def _example_trip(scored: DataFrame) -> DataFrame:
    """The legitimate traveller with the most false alarms from the naive rule: their trip."""
    worst = (
        scored.where(F.col("rule_naive") & (F.col("fraud_label") == 0))
        .groupBy("customer_id")
        .agg(F.count(F.lit(1)).alias("n"), F.min("tx_date").alias("first"), F.max("tx_date").alias("last"))
        .orderBy(F.col("n").desc(), "customer_id")
        .first()
    )
    if worst is None:
        return scored.limit(0)
    return scored.where(
        (F.col("customer_id") == worst["customer_id"])
        & F.col("is_foreign")
        & F.col("tx_date").between(F.date_sub(F.lit(worst["first"]), 4), F.date_add(F.lit(worst["last"]), 4))
    ).orderBy("ts_s", "tx_id")


def _delta_history(spark: SparkSession, path: Path) -> list[dict]:
    keep = ["numOutputRows", "numTargetRowsInserted", "numTargetRowsUpdated", "numFilesAdded", "numFilesRemoved"]
    history = DeltaTable.forPath(spark, str(path)).history().orderBy("version").collect()
    return [
        {
            "version": h["version"],
            "operation": h["operation"],
            "metrics": {k: int(v) for k, v in (h["operationMetrics"] or {}).items() if k in keep},
        }
        for h in history
    ]


def _time_travel(spark: SparkSession, path: Path) -> dict:
    """A transaction corrected by the incremental MERGE, read at version 0 and now."""
    v0 = spark.read.format("delta").option("versionAsOf", 0).load(str(path))
    now = spark.read.format("delta").load(str(path))
    changed = (
        v0.alias("a")
        .join(now.alias("b"), "tx_id")
        .where(F.col("a.amount") != F.col("b.amount"))
        .select("tx_id", F.col("a.amount").alias("before"), F.col("b.amount").alias("after"), F.col("b.ts").alias("ts"))
        .orderBy("tx_id")
    )
    example = changed.first()
    return {
        "rows_version_0": v0.count(),
        "rows_now": now.count(),
        "corrected_rows": changed.count(),
        "example": None
        if example is None
        else {
            "tx_id": example["tx_id"],
            "ts": example["ts"].isoformat(),
            "amount_before": float(example["before"]),
            "amount_after": float(example["after"]),
        },
    }


def write(
    spark: SparkSession,
    lake,
    scored: DataFrame,
    metrics: list[dict],
    batches: list[dict],
    maintenance: dict,
    out_dir: Path,
    raw_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    bronze_rows = spark.read.format("delta").load(str(lake.bronze_transactions)).count()
    silver = spark.read.format("delta").load(str(lake.silver_transactions))
    quarantine = spark.read.format("delta").load(str(lake.quarantine))
    reasons = {r["reason"]: r["n"] for r in quarantine.groupBy("reason").agg(F.count(F.lit(1)).alias("n")).collect()}
    span = silver.agg(F.min("tx_date").alias("first"), F.max("tx_date").alias("last")).first()

    summary = {
        "layers": {
            "bronze_rows": bronze_rows,
            "silver_rows": silver.count(),
            "quarantined_rows": sum(reasons.values()),
            "quarantine_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
            "customers": spark.read.format("delta").load(str(lake.silver_customers)).count(),
            "fraud_transactions": scored.where(F.col("fraud_label") == 1).count(),
            "first_day": span["first"].isoformat(),
            "last_day": span["last"].isoformat(),
            "silver_partitions": silver.select("tx_month").distinct().count(),
        },
        "batches": [{k: v for k, v in b.items() if k != "seconds"} for b in batches],
        "rules": [
            {"key": r.key, "name": r.name, "description": r.description, "realtime": r.realtime}
            for r, _ in fraud.RULES.values()
        ],
        "rule_metrics": metrics,
        "delta": {
            "silver_history": _delta_history(spark, lake.silver_transactions),
            "time_travel": _time_travel(spark, lake.silver_transactions),
            "optimize": maintenance,
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    daily = scored.groupBy("tx_date").agg(
        F.count(F.lit(1)).alias("transactions"),
        F.round(F.sum("amount_d"), 2).alias("amount"),
        F.sum("fraud_label").alias("fraud"),
        F.sum(F.col("rule_window").cast("int")).alias("alerts_window"),
        F.sum(F.col("rule_naive").cast("int")).alias("alerts_naive"),
    )
    _write_csv(out_dir / "daily.csv", _rows(daily.orderBy("tx_date")))
    _write_csv(out_dir / "burst_example.csv", _rows(_example_burst(scored).select(*FEATURE_COLUMNS)))
    _write_csv(out_dir / "trip_example.csv", _rows(_example_trip(scored).select(*FEATURE_COLUMNS)))
    alerts = scored.where(F.col("rule_window")).orderBy(F.col("ts_s").desc(), "tx_id").limit(40)
    _write_csv(
        out_dir / "recent_alerts.csv",
        _rows(
            alerts.select(
                "tx_id",
                "customer_id",
                "ts",
                "amount_d",
                "country",
                "tx_count_10m",
                F.array_join("alert_reasons", " + ").alias("reasons"),
                "fraud_label",
            )
        ),
    )
    print(f"📦 Dashboard data written to {out_dir}")
