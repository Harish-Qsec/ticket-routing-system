import pytest

from app.config import Settings, load_settings

ENV_VARS = (
    "TICKETS_DATABASE_URL",
    "TICKETS_NUM_WORKERS",
    "TICKETS_POLL_TIMEOUT",
    "TICKETS_QUEUE_MAXSIZE",
    "TICKETS_LOG_LEVEL",
)


@pytest.fixture
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_defaults_are_used_when_nothing_is_set(clean_env):
    settings = load_settings()

    assert settings == Settings()
    assert settings.num_workers == 3
    assert settings.queue_maxsize == 0
    assert settings.log_level == "INFO"
    assert settings.database_url.startswith("sqlite:///")


def test_environment_variables_override_the_defaults(clean_env):
    clean_env.setenv("TICKETS_DATABASE_URL", "sqlite:///other.db")
    clean_env.setenv("TICKETS_NUM_WORKERS", "7")
    clean_env.setenv("TICKETS_POLL_TIMEOUT", "0.5")
    clean_env.setenv("TICKETS_QUEUE_MAXSIZE", "100")
    clean_env.setenv("TICKETS_LOG_LEVEL", "debug")  # case does not matter

    assert load_settings() == Settings(
        database_url="sqlite:///other.db",
        num_workers=7,
        poll_timeout=0.5,
        queue_maxsize=100,
        log_level="DEBUG",
    )


def test_a_non_numeric_value_is_rejected(clean_env):
    clean_env.setenv("TICKETS_NUM_WORKERS", "three")

    with pytest.raises(ValueError):
        load_settings()


def test_an_unknown_log_level_is_rejected(clean_env):
    clean_env.setenv("TICKETS_LOG_LEVEL", "LOUD")

    with pytest.raises(ValueError, match="TICKETS_LOG_LEVEL"):
        load_settings()


def test_tests_run_against_a_temporary_database_by_default(tmp_path):
    # The autouse isolation fixture in conftest.py points the default here.
    assert tmp_path.as_posix() in load_settings().database_url