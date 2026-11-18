import pytest


@pytest.fixture(autouse=True)
def _no_real_database(monkeypatch):
    """Tests must never reach a real database: a local .env points at production.

    Any query a test doesn't mock fails loudly instead. Tests that mock the pool on purpose still can.
    """
    from db import queries

    def refuse(*args, **kwargs):
        raise RuntimeError("tests must not open a real database connection; mock db.queries instead")

    monkeypatch.setattr(queries, "ConnectionPool", refuse)
    monkeypatch.setattr(queries, "_pool", None)
