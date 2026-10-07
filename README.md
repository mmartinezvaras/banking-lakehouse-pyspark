# Banking Lakehouse with PySpark

[![CI](https://github.com/mmartinezvaras/banking-lakehouse-pyspark/actions/workflows/ci.yml/badge.svg)](https://github.com/mmartinezvaras/banking-lakehouse-pyspark/actions/workflows/ci.yml)

Data engineering project that simulates a bank's transaction data and builds a small lakehouse with PySpark: synthetic data generation, Parquet/Delta storage, analytics with window functions and rule-based fraud detection.

> Status: work in progress. All data is synthetic (no real customer data).

## Roadmap

- [ ] Project structure, synthetic data generator, tests and CI
- [ ] Ingestion and cleaning with PySpark
- [ ] Parquet storage with partitioning
- [ ] Delta Lake tables
- [ ] Fraud detection with window functions (lag/lead, running totals)
- [ ] Architecture diagram and documentation

## Quick start

    python3.12 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    pytest
    PYTHONPATH=src python -m banking_lakehouse.generate_data

This generates `data/raw/customers.csv` and `data/raw/transactions.csv`.

## Tech stack

Python, PySpark, Parquet, Delta Lake, pytest, GitHub Actions.
