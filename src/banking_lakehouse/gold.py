"""Gold: analytics-ready Delta tables built from Silver.

    fraud_features   every transaction with its window features and rule flags
    fraud_alerts     the transactions the real-time window rules would have flagged, and why
    customer_daily   per customer and day: count, total, foreign payments, largest, alerts
    rule_metrics     precision / recall / money stopped for each rule set

Gold is recomputed from the whole of Silver on every run: the windows look back up to 30 days,
so a new batch can change the features of earlier rows near the boundary. At this size a full
rebuild takes seconds; at bank scale it would be recomputed per affected customer and month.
"""

from __future__ import annotations

from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, LongType, StringType, StructField, StructType

from banking_lakehouse import fraud


def _write(df: DataFrame, path: Path) -> None:
    df.write.format("delta").mode("overwrite").option("overwriteSchema", True).save(str(path))


def metrics_frame(spark: SparkSession, metrics: list[dict]) -> DataFrame:
    """Explicit schema: a rule that never fires has None in some fields, which Spark can't infer."""
    sample = metrics[0]
    types = {}
    for key in sample:
        values = [m[key] for m in metrics if m[key] is not None]
        if values and all(isinstance(v, str) for v in values):
            types[key] = StringType()
        elif values and all(isinstance(v, int) for v in values):
            types[key] = LongType()
        else:
            types[key] = DoubleType() if values else LongType()
    schema = StructType([StructField(k, t, True) for k, t in types.items()])
    rows = [
        tuple(
            None if m[k] is None else (float(m[k]) if isinstance(t, DoubleType) else m[k]) for k, t in types.items()
        )
        for m in metrics
    ]
    return spark.createDataFrame(rows, schema)


def build(spark: SparkSession, silver_path: Path, gold_dir: Path) -> tuple[DataFrame, list[dict]]:
    silver = spark.read.format("delta").load(str(silver_path))
    scored = fraud.apply_rules(fraud.add_features(silver))
    _write(scored.drop("_ingested_at"), gold_dir / "fraud_features")
    scored = spark.read.format("delta").load(str(gold_dir / "fraud_features")).cache()

    alerts = scored.where(F.col("rule_window")).select(
        "tx_id", "customer_id", "ts", "amount", "country", "channel", "tx_count_10m", "alert_reasons", "fraud_label"
    )
    _write(alerts, gold_dir / "fraud_alerts")

    daily = scored.groupBy("customer_id", "tx_date").agg(
        F.count(F.lit(1)).alias("transactions"),
        F.round(F.sum("amount_d"), 2).alias("total_amount"),
        F.sum(F.col("is_foreign").cast("int")).alias("foreign_transactions"),
        F.max("amount_d").alias("largest_amount"),
        F.sum(F.col("rule_window").cast("int")).alias("alerts"),
    )
    _write(daily, gold_dir / "customer_daily")

    metrics = fraud.evaluate(scored)
    _write(metrics_frame(spark, metrics), gold_dir / "rule_metrics")
    return scored, metrics
