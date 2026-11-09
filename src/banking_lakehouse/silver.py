"""Silver: typed, cleaned, deduplicated transactions; bad rows go to quarantine with a reason.

Fixable problems are fixed:   "1.234,56" and "€ 42,10" amounts, dd/MM/yyyy timestamps,
                              " CARD_PAYMENT " casing, lower-case country codes.
Impossible rows are set aside: missing or negative amounts, unparseable dates, unknown
                              customers, unknown transaction types.
Re-delivered rows are dropped (kept once), and counted.

Spark 4 runs in ANSI mode, where casting "abc" to a number raises an error instead of
returning null, so every conversion uses the try_* functions and the nulls drive the
quarantine reasons.

The Silver table is Delta, partitioned by month (partitioning by day would create ~180 tiny
partitions for 50k rows: the small-files problem). New batches are MERGEd on tx_id, so a
corrected transaction updates its row instead of creating a second one.
"""

from __future__ import annotations

from pathlib import Path

from delta.tables import DeltaTable
from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from banking_lakehouse.schemas import CHANNELS, TX_TYPES

SILVER_COLUMNS = [
    "tx_id",
    "customer_id",
    "ts",
    "tx_date",
    "tx_month",
    "tx_type",
    "channel",
    "amount",
    "country",
    "is_foreign",
    "fraud_label",
    "_batch_id",
    "_ingested_at",
]


def _try_cast(column: str, sql_type: str) -> Column:
    return F.expr(f"try_cast({column} AS {sql_type})")


def normalise_amount_text(col: Column) -> Column:
    """'12.50' → '12.50', '1.234,56' → '1234.56', '€ 42,10' → '42.10'. Casting comes after."""
    cleaned = F.regexp_replace(F.trim(col), r"[€\s]", "")
    european = F.regexp_replace(F.regexp_replace(cleaned, r"\.", ""), ",", ".")
    return F.when(cleaned.contains(","), european).otherwise(cleaned)


def parse_timestamp(col: Column) -> Column:
    """ISO 'yyyy-MM-ddTHH:mm:ss' or 'dd/MM/yyyy HH:mm:ss'; anything else → null."""
    return F.coalesce(
        F.try_to_timestamp(col, F.lit("yyyy-MM-dd'T'HH:mm:ss")),
        F.try_to_timestamp(col, F.lit("dd/MM/yyyy HH:mm:ss")),
    )


def standardise(bronze: DataFrame) -> DataFrame:
    """Typed columns (tx_id_n, amount_n, ts, …) next to the raw strings, before any row is rejected."""
    return (
        bronze.withColumn("amount_text", normalise_amount_text(F.col("amount")))
        .withColumn("tx_id_n", _try_cast("tx_id", "BIGINT"))
        .withColumn("customer_id_n", _try_cast("customer_id", "INT"))
        .withColumn("amount_n", _try_cast("amount_text", "DECIMAL(12,2)"))
        .withColumn("ts", parse_timestamp(F.trim(F.col("timestamp"))))
        .withColumn("tx_type_n", F.lower(F.trim(F.col("tx_type"))))
        .withColumn("channel_n", F.lower(F.trim(F.col("channel"))))
        .withColumn("country_n", F.upper(F.trim(F.col("country"))))
        .withColumn("fraud_label_n", F.coalesce(_try_cast("fraud_label", "INT"), F.lit(0)))
    )


def rejection_reason(known_customer: Column) -> Column:
    return (
        F.when(F.col("tx_id_n").isNull(), "invalid_tx_id")
        .when(F.col("amount_n").isNull(), "missing_or_unparseable_amount")
        .when(F.col("amount_n") <= 0, "non_positive_amount")
        .when(F.col("ts").isNull(), "unparseable_timestamp")
        .when(~known_customer, "unknown_customer")
        .when(~F.col("tx_type_n").isin(TX_TYPES), "invalid_tx_type")
        .when(~F.col("channel_n").isin(CHANNELS), "invalid_channel")
        .when(F.coalesce(F.length("country_n"), F.lit(0)) != 2, "invalid_country")
    )


def clean_transactions(bronze: DataFrame, customers: DataFrame) -> tuple[DataFrame, DataFrame]:
    """Split a Bronze batch into (valid Silver rows, quarantined rows with a reason).

    Duplicates (same tx_id delivered more than once in the batch) keep one copy; the extra
    copies go to quarantine as "duplicate_delivery" so every Bronze row is accounted for."""
    known = customers.select(F.col("customer_id").alias("_known_id")).distinct()
    df = standardise(bronze).join(F.broadcast(known), F.col("customer_id_n") == F.col("_known_id"), "left")
    df = df.withColumn("_reason", rejection_reason(F.col("_known_id").isNotNull()))

    valid = df.where(F.col("_reason").isNull())
    first = Window.partitionBy("tx_id_n").orderBy(F.col("_ingested_at").desc(), F.col("_source_file"))
    valid = valid.withColumn("_copy", F.row_number().over(first))
    duplicates = valid.where(F.col("_copy") > 1).withColumn("_reason", F.lit("duplicate_delivery"))
    valid = valid.where(F.col("_copy") == 1)

    silver = valid.select(
        F.col("tx_id_n").alias("tx_id"),
        F.col("customer_id_n").alias("customer_id"),
        "ts",
        F.to_date("ts").alias("tx_date"),
        F.date_format("ts", "yyyy-MM").alias("tx_month"),
        F.col("tx_type_n").alias("tx_type"),
        F.col("channel_n").alias("channel"),
        F.col("amount_n").alias("amount"),
        F.col("country_n").alias("country"),
        (F.col("country_n") != "ES").alias("is_foreign"),
        F.col("fraud_label_n").alias("fraud_label"),
        "_batch_id",
        "_ingested_at",
    )
    raw_cols = ["tx_id", "customer_id", "timestamp", "tx_type", "channel", "amount", "country", "fraud_label"]
    quarantine = (
        df.where(F.col("_reason").isNotNull())
        .unionByName(duplicates.drop("_copy"), allowMissingColumns=True)
        .select(*raw_cols, F.col("_reason").alias("reason"), "_batch_id", "_source_file", "_ingested_at")
        .withColumn("_quarantined_at", F.current_timestamp())
    )
    return silver, quarantine


def clean_customers(bronze_customers: DataFrame) -> DataFrame:
    latest = Window.partitionBy("customer_id").orderBy(F.col("_ingested_at").desc())
    return (
        bronze_customers.withColumn("customer_id", _try_cast("customer_id", "INT"))
        .where(F.col("customer_id").isNotNull())
        .withColumn("_n", F.row_number().over(latest))
        .where(F.col("_n") == 1)
        .select(
            "customer_id",
            F.trim("name").alias("name"),
            F.trim("city").alias("city"),
            F.lower(F.trim("account_type")).alias("account_type"),
            F.to_date(F.try_to_timestamp(F.trim("signup_date"), F.lit("yyyy-MM-dd"))).alias("signup_date"),
            (F.coalesce(_try_cast("traveller", "INT"), F.lit(0)) == 1).alias("traveller"),
        )
    )


def upsert_transactions(spark: SparkSession, silver_batch: DataFrame, table_path: Path) -> dict[str, int]:
    """Create the Silver table or MERGE a batch into it. Returns inserted/updated row counts."""
    path = str(table_path)
    if not DeltaTable.isDeltaTable(spark, path):
        silver_batch.write.format("delta").partitionBy("tx_month").save(path)
        return {"inserted": spark.read.format("delta").load(path).count(), "updated": 0}

    target = DeltaTable.forPath(spark, path)
    changed = " OR ".join(f"NOT (t.{c} <=> s.{c})" for c in ["amount", "ts", "tx_type", "channel", "country", "customer_id"])
    (
        target.alias("t")
        .merge(silver_batch.alias("s"), "t.tx_id = s.tx_id")
        .whenMatchedUpdateAll(condition=changed)
        .whenNotMatchedInsertAll()
        .execute()
    )
    metrics = target.history(1).select("operationMetrics").first()["operationMetrics"]
    return {
        "inserted": int(metrics.get("numTargetRowsInserted", 0)),
        "updated": int(metrics.get("numTargetRowsUpdated", 0)),
    }


def append_quarantine(quarantine_batch: DataFrame, table_path: Path) -> None:
    quarantine_batch.write.format("delta").mode("append").save(str(table_path))
