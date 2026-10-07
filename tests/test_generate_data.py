import random

from faker import Faker

from banking_lakehouse.generate_data import generate_customers, generate_transactions


def test_counts_and_injected_fraud():
    rng = random.Random(1)
    Faker.seed(1)
    fake = Faker("es_ES")

    customers = generate_customers(50, rng, fake)
    transactions = generate_transactions(4000, 50, rng)

    assert len(customers) == 50
    assert len(transactions) > 4000
    assert any(t["fraud_label"] == 1 for t in transactions)
    assert all(1 <= t["customer_id"] <= 50 for t in transactions)
