import pytest


@pytest.fixture(scope="session")
def spark():
    pytest.importorskip("pyspark")
    from banking_lakehouse.spark import get_spark

    session = get_spark("tests", master="local[2]")
    session.conf.set("spark.sql.shuffle.partitions", "2")
    yield session
    session.stop()
