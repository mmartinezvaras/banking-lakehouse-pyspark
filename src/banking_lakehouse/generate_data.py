"""Synthetic bank data: customers and card/account transactions with realistic fraud and dirty data.

What makes it a useful test bed:

* Fraud is rare (about 0.2 % of rows) and comes in bursts that mimic a compromised card:
  a few tiny "card testing" payments, then a rapid series of larger online payments abroad.
* Legitimate customers also travel. Their trips produce foreign card payments, some of them
  large (hotels, car rental), so "big payment abroad" alone is not fraud. Per-customer,
  time-ordered features (window functions) are needed to tell the two apart.
* And some legitimate behaviour looks like fraud even to those features: several quick
  orders from a foreign online shop, or a €1 card-verification charge before a subscription.
  No rule set gets a perfect score, as in real life.
* The raw files are dirty the way real feeds are: re-delivered rows, amounts written as
  "1.234,56" or "€ 42,10", timestamps in two formats, inconsistent casing, and a few
  impossible rows (missing or negative amounts, unknown customers) for the Silver layer to
  quarantine. Fraud rows are only ever reformatted, never made invalid, so the ground truth
  stays measurable.
* A second, incremental batch (the next day plus corrections to earlier rows) exercises
  Delta Lake MERGE.

Everything comes from one seeded RNG, so the same seed gives byte-identical files.

    python -m banking_lakehouse.generate_data                      # 1,000 customers, ~50k transactions
    python -m banking_lakehouse.generate_data --transactions 500000  # bigger run
"""

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker

from banking_lakehouse import config

ACCOUNT_TYPES = ["checking", "savings", "business"]
FOREIGN_COUNTRIES = ["FR", "DE", "IT", "PT", "GB", "US", "MA", "CN", "BR"]
FRAUD_COUNTRIES = ["US", "CN", "BR", "NG", "RU", "GB"]
START = datetime(2026, 1, 1)
PERIOD_DAYS = 181  # 1 Jan – 30 Jun 2026
INCREMENT_DAY = datetime(2026, 7, 1)

TX_FIELDS = ["tx_id", "customer_id", "timestamp", "tx_type", "channel", "amount", "country", "fraud_label"]


@dataclass
class Tx:
    tx_id: int
    customer_id: int
    timestamp: datetime
    tx_type: str  # deposit | withdrawal | transfer | card_payment
    channel: str  # pos | online | atm | branch | app
    amount: float
    country: str
    fraud_label: int = 0

    def as_row(self) -> dict:
        return {
            "tx_id": self.tx_id,
            "customer_id": self.customer_id,
            "timestamp": self.timestamp.strftime("%Y-%m-%dT%H:%M:%S"),
            "tx_type": self.tx_type,
            "channel": self.channel,
            "amount": f"{self.amount:.2f}",
            "country": self.country,
            "fraud_label": self.fraud_label,
        }


# ------------------------------------------------------------------------------------------
# Customers
# ------------------------------------------------------------------------------------------


def generate_customers(n: int, rng: random.Random, fake: Faker) -> list[dict]:
    """``n`` customer profiles. About 1 in 8 is a frequent traveller."""
    customers = []
    for customer_id in range(1, n + 1):
        signup = datetime(2016, 1, 1) + timedelta(days=rng.randint(0, 3600))
        customers.append(
            {
                "customer_id": customer_id,
                "name": fake.name(),
                "city": fake.city(),
                "account_type": rng.choices(ACCOUNT_TYPES, weights=[70, 22, 8])[0],
                "signup_date": signup.date().isoformat(),
                "traveller": int(rng.random() < 0.125),
            }
        )
    return customers


# ------------------------------------------------------------------------------------------
# Transactions
# ------------------------------------------------------------------------------------------


def _random_time(rng: random.Random, day: datetime) -> datetime:
    """A time of day weighted towards daytime and evening."""
    hour = rng.choices(range(24), weights=[1, 1, 1, 1, 1, 2, 3, 5, 7, 8, 8, 8, 9, 9, 8, 8, 8, 9, 10, 10, 8, 6, 4, 2])[0]
    return day.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59))


def _everyday_tx(rng: random.Random, customer_id: int, ts: datetime) -> tuple[str, str, float, str]:
    """(tx_type, channel, amount, country) of an ordinary transaction at home."""
    kind = rng.choices(["card_payment", "withdrawal", "transfer", "deposit"], weights=[72, 12, 10, 6])[0]
    if kind == "card_payment":
        channel = rng.choices(["pos", "online"], weights=[70, 30])[0]
        # Mostly small, sometimes a big purchase (electronics, furniture).
        amount = rng.uniform(600, 2200) if rng.random() < 0.004 else rng.lognormvariate(3.3, 0.95)
    elif kind == "withdrawal":
        channel = "atm"
        amount = rng.choice([20, 40, 50, 60, 100, 150, 200, 300])
    elif kind == "transfer":
        channel = rng.choice(["app", "online", "branch"])
        amount = rng.lognormvariate(5.0, 1.0)
    else:
        channel = rng.choice(["branch", "app"])
        amount = rng.uniform(900, 3200) if rng.random() < 0.5 else rng.lognormvariate(4.5, 1.0)
    # Small online purchases from foreign shops happen at home too.
    country = rng.choice(FOREIGN_COUNTRIES) if channel == "online" and rng.random() < 0.08 else "ES"
    return kind, channel, round(max(amount, 0.5), 2), country


def _trip(rng: random.Random, customer_id: int, day0: datetime) -> list[tuple]:
    """A legitimate trip abroad: several days of card payments in one country, some of them large
    (hotel, car rental). This is what a naive "big payment abroad" rule mistakes for fraud."""
    country = rng.choice(FOREIGN_COUNTRIES)
    rows = []
    for d in range(rng.randint(3, 9)):
        day = day0 + timedelta(days=d)
        for _ in range(rng.randint(1, 4)):
            ts = _random_time(rng, day)
            channel = "atm" if rng.random() < 0.1 else "pos"
            kind = "withdrawal" if channel == "atm" else "card_payment"
            if channel == "atm":
                amount = rng.choice([50, 100, 150, 200, 300])
            elif rng.random() < 0.12:
                amount = rng.uniform(350, 1800)  # hotel, car rental, flight change
            else:
                amount = rng.lognormvariate(3.6, 0.9)
            rows.append((customer_id, ts, kind, channel, round(amount, 2), country))
    return rows


def _online_spree(rng: random.Random, customer_id: int, t0: datetime) -> list[tuple]:
    """Legitimate: several purchases from a foreign online shop within minutes (a basket split
    into orders, game credits…). Looks like velocity fraud."""
    country = rng.choice(FOREIGN_COUNTRIES)
    rows, t = [], t0
    for _ in range(rng.randint(2, 5)):
        rows.append((customer_id, t, "card_payment", "online", round(rng.lognormvariate(3.6, 0.8), 2), country))
        t += timedelta(seconds=rng.randint(40, 240))
    return rows


def _card_verification(rng: random.Random, customer_id: int, t0: datetime) -> list[tuple]:
    """Legitimate: a foreign service charges €1 to verify the card, then the real price.
    Looks like card testing."""
    country = rng.choice(["US", "GB", "IE", "NL"])
    return [
        (customer_id, t0, "card_payment", "online", 1.0, country),
        (customer_id, t0 + timedelta(seconds=rng.randint(45, 400)), "card_payment", "online", round(rng.uniform(100, 450), 2), country),
    ]


def _fraud_burst(rng: random.Random, customer_id: int, t0: datetime) -> list[tuple]:
    """A compromised card: 1–3 tiny "card testing" payments, then 3–6 larger online payments,
    each 30 s – 3 min after the previous one, sometimes hopping between countries."""
    rows = []
    t = t0
    country = rng.choice(FRAUD_COUNTRIES)
    for _ in range(rng.randint(1, 3)):
        rows.append((customer_id, t, "card_payment", "online", round(rng.uniform(0.5, 3.0), 2), country))
        t += timedelta(seconds=rng.randint(30, 180))
    # Some fraudsters stay under typical "large payment" thresholds.
    low, high = (350, 880) if rng.random() < 0.35 else (900, 2800)
    for _ in range(rng.randint(3, 6)):
        if rng.random() < 0.25:
            country = rng.choice(FRAUD_COUNTRIES)
        rows.append((customer_id, t, "card_payment", "online", round(rng.uniform(low, high), 2), country))
        t += timedelta(seconds=rng.randint(30, 180))
    return rows


def generate_transactions(
    n: int, customers: list[dict], rng: random.Random, start: datetime = START, days: int = PERIOD_DAYS
) -> list[Tx]:
    """About ``n`` legitimate transactions (everyday spending plus trips) and fraud bursts in
    proportion (one per ~4,000 transactions), sorted by time, with IDs assigned in time order."""
    n_customers = len(customers)
    travellers = [c["customer_id"] for c in customers if c["traveller"]] or [1]
    raw: list[tuple] = []

    # Trips: travellers take a few per half-year; everyone else rarely. (A one-day batch has none:
    # a trip lasts several days.)
    n_trips = max(1, n // 400) if days >= 10 else 0
    for _ in range(n_trips):
        cid = rng.choice(travellers) if rng.random() < 0.8 else rng.randint(1, n_customers)
        day0 = start + timedelta(days=rng.randint(0, max(days - 10, 0)))
        raw += [r + (0,) for r in _trip(rng, cid, day0)]

    # Legitimate patterns that look like fraud to simple velocity / card-testing rules.
    for _ in range(max(1, n // 1200)):
        t0 = _random_time(rng, start + timedelta(days=rng.randrange(days)))
        raw += [r + (0,) for r in _online_spree(rng, rng.randint(1, n_customers), t0)]
    for _ in range(max(1, n // 4000)):
        t0 = _random_time(rng, start + timedelta(days=rng.randrange(days)))
        raw += [r + (0,) for r in _card_verification(rng, rng.randint(1, n_customers), t0)]

    # Everyday transactions fill the rest.
    while len(raw) < n:
        cid = rng.randint(1, n_customers)
        ts = _random_time(rng, start + timedelta(days=rng.randrange(days)))
        raw.append((cid, ts, *_everyday_tx(rng, cid, ts), 0))

    for _ in range(max(1, n // 4000)):
        cid = rng.randint(1, n_customers)
        t0 = _random_time(rng, start + timedelta(days=rng.randrange(days)))
        raw += [r + (1,) for r in _fraud_burst(rng, cid, t0)]

    raw.sort(key=lambda r: (r[1], r[0]))
    return [Tx(i, cid, ts, kind, ch, amt, country, label) for i, (cid, ts, kind, ch, amt, country, label) in enumerate(raw, 1)]


def generate_increment(
    previous: list[Tx], customers: list[dict], rng: random.Random, n: int, day: datetime = INCREMENT_DAY
) -> list[Tx]:
    """The next day's batch: new transactions (with one fraud burst) plus corrections, i.e.
    earlier transactions re-sent with a corrected amount. MERGE must update those, not duplicate them."""
    batch = generate_transactions(n, customers, rng, start=day, days=1)
    next_id = max(t.tx_id for t in previous) + 1
    for offset, tx in enumerate(batch):
        tx.tx_id = next_id + offset
    legit = [t for t in previous if not t.fraud_label and t.tx_type == "card_payment"]
    for old in rng.sample(legit, k=min(25, len(legit))):
        batch.append(
            Tx(old.tx_id, old.customer_id, old.timestamp, old.tx_type, old.channel, round(old.amount * 0.9, 2), old.country)
        )
    return batch


# ------------------------------------------------------------------------------------------
# Dirty data
# ------------------------------------------------------------------------------------------


def _eu_amount(value: float) -> str:
    """1234.5 → '1.234,50'"""
    whole, cents = f"{value:.2f}".split(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return ".".join(groups) + "," + cents


def dirty_rows(transactions: list[Tx], rng: random.Random, n_customers: int) -> list[dict]:
    """CSV rows with the problems real feeds have. Returns the rows to write (with duplicates)."""
    rows = []
    for tx in transactions:
        row = tx.as_row()
        r = rng.random()
        # Formatting problems Silver must fix (any row, fraud included).
        if r < 0.004:
            row["amount"] = _eu_amount(tx.amount)
        elif r < 0.006:
            row["amount"] = "€ " + _eu_amount(tx.amount)
        if rng.random() < 0.006:
            row["timestamp"] = tx.timestamp.strftime("%d/%m/%Y %H:%M:%S")
        if rng.random() < 0.01:
            row["tx_type"] = f" {tx.tx_type.upper()} "
        if rng.random() < 0.01:
            row["country"] = tx.country.lower()
        # Impossible values Silver must quarantine (never on fraud rows).
        if not tx.fraud_label:
            r = rng.random()
            if r < 0.002:
                row["amount"] = ""
            elif r < 0.003:
                row["amount"] = f"-{tx.amount:.2f}"
            elif r < 0.0045:
                row["customer_id"] = n_customers + rng.randint(1000, 9999)
            elif r < 0.005:
                row["timestamp"] = "not-a-date"
        rows.append(row)
        # Re-delivered records (the source system sent them twice).
        if rng.random() < 0.01:
            rows.append(dict(row))
    return rows


# ------------------------------------------------------------------------------------------
# Writing
# ------------------------------------------------------------------------------------------


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def generate(
    raw_dir: Path = config.RAW_DIR, n_customers: int = 1000, n_transactions: int = 50_000, seed: int = config.SEED
) -> dict[str, int]:
    """Write customers.csv, the first transactions batch and the incremental batch."""
    rng = random.Random(seed)
    Faker.seed(seed)
    fake = Faker("es_ES")

    customers = generate_customers(n_customers, rng, fake)
    history = generate_transactions(n_transactions, customers, rng)
    increment = generate_increment(history, customers, rng, n=max(200, n_transactions // 180))

    write_csv(raw_dir / "customers.csv", customers)
    batch1 = dirty_rows(history, rng, n_customers)
    batch2 = dirty_rows(increment, rng, n_customers)
    write_csv(raw_dir / "transactions" / config.BATCH_1, batch1, TX_FIELDS)
    write_csv(raw_dir / "increments" / config.BATCH_2, batch2, TX_FIELDS)

    stats = {
        "customers": len(customers),
        "transactions": len(history),
        "fraud_transactions": sum(t.fraud_label for t in history),
        "raw_rows_batch_1": len(batch1),
        "raw_rows_batch_2": len(batch2),
    }
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic bank dataset.")
    parser.add_argument("--customers", type=int, default=1000)
    parser.add_argument("--transactions", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=config.SEED)
    parser.add_argument("--out", type=Path, default=config.RAW_DIR)
    args = parser.parse_args()
    stats = generate(args.out, args.customers, args.transactions, args.seed)
    print(" | ".join(f"{k}: {v:,}" for k, v in stats.items()))


if __name__ == "__main__":
    main()
