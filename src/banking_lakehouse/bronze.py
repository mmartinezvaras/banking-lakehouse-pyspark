"""Bronze: land the raw files as they are, plus audit columns.

Every column stays a string (see schemas.py): Bronze is the faithful copy of what the source
sent, so any later bug can be fixed by re-running Silver, never by asking the source again.
Each load records which file it came from, when, and under which batch ID, and a batch that
is already in Bronze is skipped, so re-running the pipeline never duplicates data.
"""

from __future__ import annotations

from pathlib import Path

from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from banking_lakehouse.schemas import RAW_CUSTOMERS, RAW_TRANSACTIONS


def _read_csv(spark: SparkSession, path: Path, schema) -> DataFrame:
    return (
        spark.read.option("header", True)
        .option("mode", "PERMISSIVE")
        .schema(schema)
        .csv(str(path))
        .select("*", F.col("_metadata.file_name").alias("_source_file"))
    )


def batch_ingested(spark: SparkSession, table_path: Path, batch_id: str) -> bool:
    if not DeltaTable.isDeltaTable(spark, str(table_path)):
        return False
    return spark.read.format("delta").load(str(table_path)).where(F.col("_batch_id") == batch_id).limit(1).count() > 0


def ingest_transactions(spark: SparkSession, csv_path: Path, table_path: Path, batch_id: str) -> int:
    """Append one raw transactions file to Bronze. Returns the rows added (0 if already loaded)."""
    if batch_ingested(spark, table_path, batch_id):
        return 0
    df = (
        _read_csv(spark, csv_path, RAW_TRANSACTIONS)
        .withColumn("_batch_id", F.lit(batch_id))
        .withColumn("_ingested_at", F.current_timestamp())
    )
    df.write.format("delta").mode("append").save(str(table_path))
    return spark.read.format("delta").load(str(table_path)).where(F.col("_batch_id") == batch_id).count()


def ingest_customers(spark: SparkSession, csv_path: Path, table_path: Path) -> int:
    """Customers are a full snapshot each time: overwrite."""
    df = _read_csv(spark, csv_path, RAW_CUSTOMERS).withColumn("_ingested_at", F.current_timestamp())
    df.write.format("delta").mode("overwrite").option("overwriteSchema", True).save(str(table_path))
    return df.count()
