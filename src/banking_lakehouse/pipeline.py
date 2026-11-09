"""Run the lakehouse end to end: raw CSV → Bronze → Silver (+ quarantine) → Gold, then Delta
maintenance and the export for the dashboard.

    python -m banking_lakehouse.pipeline              # process every raw batch not yet loaded
    python -m banking_lakehouse.pipeline --no-export  # skip writing dashboard/data

Batches are processed in order: data/raw/transactions/*.csv (the initial load), then
data/raw/increments/*.csv (later days, MERGEd). Re-running is safe: batches already in Bronze
are skipped, and Gold is rebuilt from Silver.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path

from delta.tables import DeltaTable
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from banking_lakehouse import bronze, config, gold, silver


@dataclass(frozen=True)
class Lake:
    root: Path

    @property
    def bronze_transactions(self) -> Path:
        return self.root / "bronze" / "transactions"

    @property
    def bronze_customers(self) -> Path:
        return self.root / "bronze" / "customers"

    @property
    def silver_transactions(self) -> Path:
        return self.root / "silver" / "transactions"

    @property
    def silver_customers(self) -> Path:
        return self.root / "silver" / "customers"

    @property
    def quarantine(self) -> Path:
        return self.root / "silver" / "quarantine"

    @property
    def gold(self) -> Path:
        return self.root / "gold"


def raw_batches(raw_dir: Path) -> list[Path]:
    return sorted((raw_dir / "transactions").glob("*.csv")) + sorted((raw_dir / "increments").glob("*.csv"))


def process_batches(spark: SparkSession, raw_dir: Path, lake: Lake) -> list[dict]:
    bronze.ingest_customers(spark, raw_dir / "customers.csv", lake.bronze_customers)
    customers = silver.clean_customers(spark.read.format("delta").load(str(lake.bronze_customers)))
    customers.write.format("delta").mode("overwrite").option("overwriteSchema", True).save(str(lake.silver_customers))
    customers = spark.read.format("delta").load(str(lake.silver_customers))

    report = []
    for csv_path in raw_batches(raw_dir):
        batch_id = csv_path.stem
        started = time.perf_counter()
        added = bronze.ingest_transactions(spark, csv_path, lake.bronze_transactions, batch_id)
        if not added:
            print(f"⏭️  {batch_id}: already loaded")
            continue
        batch = spark.read.format("delta").load(str(lake.bronze_transactions)).where(F.col("_batch_id") == batch_id)
        valid, rejected = silver.clean_transactions(batch, customers)
        merged = silver.upsert_transactions(spark, valid, lake.silver_transactions)
        silver.append_quarantine(rejected, lake.quarantine)
        quarantined = spark.read.format("delta").load(str(lake.quarantine)).where(F.col("_batch_id") == batch_id).count()
        entry = {
            "batch": batch_id,
            "bronze_rows": added,
            "inserted": merged["inserted"],
            "updated": merged["updated"],
            "quarantined": quarantined,
            "seconds": round(time.perf_counter() - started, 1),
        }
        print(f"✅ {batch_id}: {entry}")
        report.append(entry)
    return report


def optimize(spark: SparkSession, lake: Lake) -> dict:
    """Compact Silver's small files and Z-order the features table by customer (most queries
    filter by customer, so their rows end up in fewer files)."""
    out = {}
    for name, path, zorder in [
        ("silver_transactions", lake.silver_transactions, None),
        ("gold_fraud_features", lake.gold / "fraud_features", "customer_id"),
    ]:
        table = DeltaTable.forPath(spark, str(path))
        result = table.optimize().executeZOrderBy(zorder) if zorder else table.optimize().executeCompaction()
        metrics = result.select("metrics.numFilesAdded", "metrics.numFilesRemoved").first()
        out[name] = {"files_removed": int(metrics["numFilesRemoved"]), "files_added": int(metrics["numFilesAdded"])}
    return out


def run(
    raw_dir: Path = config.RAW_DIR,
    lake_dir: Path = config.LAKE_DIR,
    export_dir: Path | None = config.EXPORT_DIR,
    spark: SparkSession | None = None,
) -> dict:
    if spark is None:
        from banking_lakehouse.spark import get_spark

        spark = get_spark()
    lake = Lake(Path(lake_dir))
    batches = process_batches(spark, Path(raw_dir), lake)
    scored, metrics = gold.build(spark, lake.silver_transactions, lake.gold)
    maintenance = optimize(spark, lake) if batches else {}

    summary = {"batches": batches, "rule_metrics": metrics, "optimize": maintenance}
    for m in metrics:
        print(
            f"📊 {m['name']}: precision {m['precision']:.0%}, recall {m['recall']:.0%}, "
            f"money stopped {m['share_stopped']:.0%}, false alerts/day {m['false_alerts_per_day']}"
        )
    if export_dir is not None:
        from banking_lakehouse import export

        export.write(spark, lake, scored, metrics, batches, maintenance, Path(export_dir), Path(raw_dir))
    scored.unpersist()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, default=config.RAW_DIR)
    parser.add_argument("--lake", type=Path, default=config.LAKE_DIR)
    parser.add_argument("--no-export", action="store_true")
    args = parser.parse_args()
    summary = run(args.raw, args.lake, None if args.no_export else config.EXPORT_DIR)
    print(json.dumps(summary["batches"], indent=2))


if __name__ == "__main__":
    main()
