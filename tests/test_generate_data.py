"""The generator: reproducible, realistic fraud and travel patterns, and dirty raw rows."""

import csv
import random
from datetime import timedelta

import pytest
from faker import Faker

from banking_lakehouse.generate_data import (
    dirty_rows,
    generate,
    generate_customers,
    generate_increment,
    generate_transactions,
)


@pytest.fixture(scope="module")
def data():
    rng = random.Random(7)
    Faker.seed(7)
    customers = generate_customers(200, rng, Faker("es_ES"))
    txs = generate_transactions(12_000, customers, rng)
    return customers, txs, rng


def test_counts_ids_and_order(data):
    customers, txs, _ = data
    assert len(customers) == 200
    assert len(txs) > 12_000
    assert [t.tx_id for t in txs] == list(range(1, len(txs) + 1))
    assert all(a.timestamp <= b.timestamp for a, b in zip(txs, txs[1:]))
    assert all(1 <= t.customer_id <= 200 for t in txs)


def test_fraud_is_rare_and_comes_in_tight_bursts(data):
    _, txs, _ = data
    fraud = [t for t in txs if t.fraud_label]
    assert 0.001 < len(fraud) / len(txs) < 0.005
    by_customer = {}
    for t in fraud:
        by_customer.setdefault(t.customer_id, []).append(t)
    for rows in by_customer.values():
        rows.sort(key=lambda t: t.timestamp)
        gaps = [(b.timestamp - a.timestamp) for a, b in zip(rows, rows[1:])]
        # Within a burst payments are 30 s – 3 min apart (bursts of one customer can be days apart).
        assert all(timedelta(seconds=30) <= g <= timedelta(seconds=180) or g > timedelta(hours=1) for g in gaps)
    assert all(t.tx_type == "card_payment" and t.channel == "online" and t.country != "ES" for t in fraud)
    # Card testing: every burst starts with a tiny probe.
    assert min(t.amount for t in fraud) < 5


def test_legitimate_customers_also_pay_big_abroad(data):
    _, txs, _ = data
    legit_big_abroad = [t for t in txs if not t.fraud_label and t.country != "ES" and t.amount > 900]
    assert len(legit_big_abroad) >= 5, "travellers should trip a naive 'big payment abroad' rule"


def test_same_seed_same_files(tmp_path):
    a = generate(tmp_path / "a", n_customers=50, n_transactions=3000, seed=3)
    b = generate(tmp_path / "b", n_customers=50, n_transactions=3000, seed=3)
    assert a == b
    for rel in ["customers.csv", "transactions/2026-H1.csv", "increments/2026-07-01.csv"]:
        assert (tmp_path / "a" / rel).read_bytes() == (tmp_path / "b" / rel).read_bytes()


def test_dirty_rows_keep_fraud_valid(data):
    customers, txs, rng = data
    rows = dirty_rows(txs, random.Random(1), len(customers))
    assert len(rows) > len(txs)  # re-delivered duplicates
    amounts = [r["amount"] for r in rows]
    assert any("," in a for a in amounts) and any(a.startswith("€") for a in amounts)
    assert any(a == "" for a in amounts) and any(a.startswith("-") for a in amounts)
    assert any("/" in r["timestamp"] for r in rows)
    fraud_rows = [r for r in rows if r["fraud_label"] == 1]
    assert all(r["amount"] and not r["amount"].startswith("-") for r in fraud_rows)
    assert all(int(r["customer_id"]) <= len(customers) for r in fraud_rows)


def test_increment_has_new_rows_and_corrections(data):
    customers, txs, rng = data
    inc = generate_increment(txs, customers, random.Random(2), n=300)
    old_ids = {t.tx_id for t in txs}
    corrections = [t for t in inc if t.tx_id in old_ids]
    new = [t for t in inc if t.tx_id not in old_ids]
    assert len(corrections) == 25 and len(new) >= 300
    assert min(t.tx_id for t in new) == max(old_ids) + 1
    original = {t.tx_id: t for t in txs}
    assert all(c.amount != original[c.tx_id].amount for c in corrections)


def test_cli_files_have_headers(tmp_path):
    generate(tmp_path, n_customers=30, n_transactions=1000, seed=1)
    with open(tmp_path / "transactions" / "2026-H1.csv") as f:
        header = next(csv.reader(f))
    assert header == ["tx_id", "customer_id", "timestamp", "tx_type", "channel", "amount", "country", "fraud_label"]
