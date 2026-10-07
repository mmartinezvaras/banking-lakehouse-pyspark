import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker

ACCOUNT_TYPES = ["checking", "savings", "business"]
TX_TYPES = ["deposit", "withdrawal", "transfer", "card_payment"]
FOREIGN_COUNTRIES = ["FR", "DE", "US", "CN", "BR"]
PERIOD_SECONDS = 60 * 60 * 24 * 180  # ~6 meses


def generate_customers(n, rng, fake):
    """Devuelve una lista de n diccionarios, uno por cliente."""
    customers = []
    for customer_id in range(1, n + 1):
        customers.append(
            {
                "customer_id": customer_id,
                "name": fake.name(),          # método de Faker
                "city": fake.city(),          # método de Faker
                "account_type": rng.choice(ACCOUNT_TYPES),  # elegir uno de ACCOUNT_TYPES con rng
                "signup_date": (datetime(2018, 1, 1) + timedelta(days=rng.randint(0, 2500))).date().isoformat(),
            }
        )
    return customers


def generate_transactions(n, n_customers, rng):
    """Devuelve n transacciones normales + ráfagas de fraude, ordenadas por timestamp."""
    start = datetime(2026, 1, 1)
    rows = []

    # 1) Transacciones normales
    for tx_id in range(1, n + 1):
        rows.append(
            {
                "tx_id": tx_id,
                "customer_id": rng.randint(1, n_customers),   # cliente aleatorio entre 1 y n_customers
                "tx_type": rng.choice(TX_TYPES),       # uno de TX_TYPES
                "amount": round(rng.lognormvariate(3.5, 1.0), 2),        # log-normal, redondeado a 2 decimales
                "timestamp": start + timedelta(seconds=rng.randint(0, PERIOD_SECONDS)),     # start + segundos aleatorios dentro de PERIOD_SECONDS
                "country": "ES" if rng.random() < 0.95 else rng.choice(FOREIGN_COUNTRIES),       # "ES" casi siempre, a veces un país extranjero
                "fraud_label": 0,
            }
        )

    # 2) Ráfagas de fraude
    next_id = n + 1
    N_BURSTS = max(1, n // 5000)  # proporcional a n, mínimo 1

    for _ in range(N_BURSTS):
        # 1. Elegir cliente e instante t0 inicial
        customer_id = rng.randint(1, n_customers)
        t0 = start + timedelta(seconds=rng.randint(0, PERIOD_SECONDS))

        # 2. Bucle de 4 a 8 transacciones sospechosas
        num_frauds = rng.randint(4, 8)
        for k in range(num_frauds):
            # Calcular la fecha/hora sumando entre 60 y 180 segundos por cada iteración k
            t_fraud = t0 + timedelta(seconds=k * rng.randint(60, 180))

            rows.append(
                {
                    "tx_id": next_id,
                    "customer_id": customer_id,
                    "tx_type": "card_payment",
                    "amount": round(rng.uniform(900, 3000), 2),
                    "timestamp": t_fraud,
                    "country": rng.choice(FOREIGN_COUNTRIES),
                    "fraud_label": 1,
                }
            )
            next_id += 1

    # 3) Ordenar por timestamp
    rows.sort(key=lambda x: x["timestamp"])
    return rows


def write_csv(path, rows):
    """Escribe una lista de diccionarios en un CSV con cabecera."""
    if not rows:
        return

    # 1. Crear el directorio si no existe usando pathlib
    path.parent.mkdir(parents=True, exist_ok=True)

    # 2. Extraer los nombres de las columnas desde el primer diccionario
    fieldnames = list(rows[0].keys())

    # 3. Abrir el archivo y configurar csv.DictWriter
    with open(path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            # Hacemos copia del diccionario para no alterar el original
            row_copy = row.copy()
            
            # Convertir timestamp a string en formato ISO si es de tipo datetime
            if isinstance(row_copy.get("timestamp"), datetime):
                row_copy["timestamp"] = row_copy["timestamp"].isoformat()

            writer.writerow(row_copy)


def main():
    SEED = 42
    rng = random.Random(SEED)
    Faker.seed(SEED)
    fake = Faker("es_ES")  # locale español de España corregido

    customers = generate_customers(1000, rng, fake)
    transactions = generate_transactions(50000, 1000, rng)
    write_csv(Path("data/raw") / "customers.csv", customers)
    write_csv(Path("data/raw") / "transactions.csv", transactions)
    print(f"customers: {len(customers)} | transactions: {len(transactions)}")


if __name__ == "__main__":
    main()