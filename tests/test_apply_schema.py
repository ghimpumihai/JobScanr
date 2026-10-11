from unittest.mock import patch

from scripts import apply_schema


def test_apply_schema_main_success():
    with (
        patch("sys.argv", ["apply_schema"]),
        patch("config.load_environment") as mock_env,
        patch("db.queries.apply_schema") as mock_apply,
    ):
        ret = apply_schema.main()
        assert ret == 0
        mock_env.assert_called_once_with(staging=False)
        mock_apply.assert_called_once()


def test_apply_schema_main_staging():
    with (
        patch("sys.argv", ["apply_schema", "--staging"]),
        patch("config.load_environment") as mock_env,
        patch("db.queries.apply_schema") as mock_apply,
    ):
        ret = apply_schema.main()
        assert ret == 0
        mock_env.assert_called_once_with(staging=True)
        mock_apply.assert_called_once()


def test_apply_schema_main_failure():
    with (
        patch("sys.argv", ["apply_schema"]),
        patch("config.load_environment"),
        patch("db.queries.apply_schema", side_effect=RuntimeError("DB down")),
    ):
        ret = apply_schema.main()
        assert ret == 1
