import psycopg
import psycopg_pool
import pytest

_MESSAGE = "unit test tried to reach a real database"


def _refuse(*args, **kwargs):
    # pytest.fail raises a BaseException, so code under test that catches Exception cannot swallow it.
    pytest.fail(_MESSAGE, pytrace=True)


@pytest.fixture(autouse=True)
def _no_real_database(request, monkeypatch):
    """config.py loads the production DATABASE_URL from .env; block any connection outside integration tests."""
    if request.node.get_closest_marker("integration"):
        return
    monkeypatch.setattr(psycopg_pool.ConnectionPool, "__init__", _refuse)
    monkeypatch.setattr(psycopg.Connection, "connect", _refuse)
    monkeypatch.setattr(psycopg, "connect", _refuse)
