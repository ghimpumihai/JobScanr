from unittest.mock import MagicMock, patch
import pytest

import config
from db import queries


@pytest.fixture(autouse=True)
def reset_pool(monkeypatch):
    queries.close_pool()
    yield
    queries.close_pool()


def test_get_pool_raises_without_database_url(monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "")
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        queries.get_pool()


def test_get_pool_creates_and_caches_connection_pool(monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    mock_pool = MagicMock()
    mock_pool.closed = False

    with patch("db.queries.ConnectionPool", return_value=mock_pool) as mock_pool_cls:
        pool1 = queries.get_pool()
        mock_pool_cls.assert_called_once_with(
            conninfo="postgresql://user:pass@localhost:5432/testdb",
            min_size=1,
            max_size=10,
            open=True,
        )
        assert pool1 is mock_pool

        # Second call reuses the cached pool
        pool2 = queries.get_pool()
        assert pool2 is mock_pool
        assert mock_pool_cls.call_count == 1


def test_get_pool_recreates_when_url_changes(monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://user:pass@localhost:5432/db1")
    mock_pool1 = MagicMock()
    mock_pool1.closed = False
    mock_pool2 = MagicMock()
    mock_pool2.closed = False

    with patch("db.queries.ConnectionPool", side_effect=[mock_pool1, mock_pool2]) as mock_pool_cls:
        queries.get_pool()
        assert mock_pool_cls.call_count == 1

        monkeypatch.setattr(config, "DATABASE_URL", "postgresql://user:pass@localhost:5432/db2")
        pool2 = queries.get_pool()
        assert pool2 is mock_pool2
        assert mock_pool_cls.call_count == 2
        mock_pool1.close.assert_called_once()


def test_get_connection_delegates_to_pool(monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
    mock_pool = MagicMock()
    mock_pool.closed = False
    mock_conn_ctx = MagicMock()
    mock_pool.connection.return_value = mock_conn_ctx

    with patch("db.queries.get_pool", return_value=mock_pool):
        ctx = queries.get_connection(timeout=5.0)
        mock_pool.connection.assert_called_once_with(timeout=5.0)
        assert ctx is mock_conn_ctx


def test_close_pool():
    mock_pool = MagicMock()
    mock_pool.closed = False
    queries._pool = mock_pool
    queries._pool_conninfo = "some-url"

    queries.close_pool()
    mock_pool.close.assert_called_once()
    assert queries._pool is None
    assert queries._pool_conninfo is None


def test_delete_stale_jobs_default_days():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.rowcount = 42
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        deleted = queries.delete_stale_jobs()

        mock_cur.execute.assert_called_once_with(
            "DELETE FROM job_postings WHERE last_seen_at < NOW() - make_interval(days => %s)",
            (30,),
        )
        assert deleted == 42


def test_delete_stale_jobs_custom_days():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.rowcount = 5
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        deleted = queries.delete_stale_jobs(days=14)

        mock_cur.execute.assert_called_once_with(
            "DELETE FROM job_postings WHERE last_seen_at < NOW() - make_interval(days => %s)",
            (14,),
        )
        assert deleted == 5
