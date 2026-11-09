"""Schemas. Bronze reads every column as a string: nothing is lost or guessed at ingestion,
and typing (with explicit rules for bad values) happens in Silver."""

from pyspark.sql.types import StringType, StructField, StructType

RAW_TRANSACTION_COLUMNS = ["tx_id", "customer_id", "timestamp", "tx_type", "channel", "amount", "country", "fraud_label"]
RAW_CUSTOMER_COLUMNS = ["customer_id", "name", "city", "account_type", "signup_date", "traveller"]

RAW_TRANSACTIONS = StructType([StructField(c, StringType(), True) for c in RAW_TRANSACTION_COLUMNS])
RAW_CUSTOMERS = StructType([StructField(c, StringType(), True) for c in RAW_CUSTOMER_COLUMNS])

TX_TYPES = ["deposit", "withdrawal", "transfer", "card_payment"]
CHANNELS = ["pos", "online", "atm", "branch", "app"]
