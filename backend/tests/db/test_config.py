"""Settings guards: TLS for remote databases (SR3-02), the environment lockdown (SR3-03), https
endpoints (SR3-10 / SR2-12), `.env` handling (SR3-03 / SR2-18). No database needed."""

from __future__ import annotations

import logging
import os
import stat

import pytest
from pydantic import ValidationError

from app import config
from app.config import (
    ConfigError,
    Settings,
    check_database_tls,
    describe_database_target,
    get_settings,
    is_loopback_host,
    parse_database_url,
)

SECRET = "Zq7-very-secret-pw"  # noqa: S105 - distinctive, to prove it never reaches an error
REMOTE = f"postgresql+psycopg://app:{SECRET}@db.example.supabase.co:5432/postgres"
GOOD_DEMO = f"{REMOTE}?sslmode=require"


def make(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


def error_text(**kwargs: object) -> str:
    with pytest.raises(ValidationError) as excinfo:
        make(**kwargs)
    return str(excinfo.value)


@pytest.fixture(autouse=True)
def _no_ambient_database_url(monkeypatch):
    """conftest exports DATABASE_URL (the test DB); these tests build Settings from kwargs."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)


# --- SR3-02: TLS --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@localhost:5433/db",
        "postgresql+psycopg://u:p@127.0.0.1:5433/db",
        "postgresql+psycopg://u:p@127.0.0.2:5433/db",
        "postgresql+psycopg://u:p@[::1]:5433/db",
        "postgresql+psycopg://u:p@/db?host=/var/run/postgresql",
        "postgresql+psycopg:///db",  # default unix socket
    ],
)
def test_loopback_hosts_need_no_tls(url):
    assert make(database_url=url).database_url.get_secret_value() == url


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_remote_host_with_tls_mode_is_accepted(mode):
    url = f"{REMOTE}?sslmode={mode}"
    assert make(database_url=url).database_url.get_secret_value() == url


@pytest.mark.parametrize("suffix", ["", "?sslmode=prefer", "?sslmode=allow", "?sslmode=disable"])
def test_remote_host_without_tls_is_refused(suffix):
    message = error_text(database_url=REMOTE + suffix)
    assert "sslmode=require" in message and "without TLS" in message


def test_one_remote_host_among_local_ones_needs_tls():
    url = "postgresql+psycopg://u:p@localhost/db?host=localhost,db.example.org"
    assert "without TLS" in error_text(database_url=url)
    assert make(database_url=url + "&sslmode=verify-full")


def test_look_alike_hostnames_are_not_loopback():
    for host in ("localhost.evil.example", "127.0.0.1.evil.example", "host.docker.internal"):
        assert not is_loopback_host(host)
    assert is_loopback_host("LOCALHOST") and is_loopback_host("::1") and is_loopback_host("[::1]")


def test_test_database_url_also_needs_tls_when_remote():
    assert "TEST_DATABASE_URL" in error_text(test_database_url=REMOTE)
    assert make(test_database_url=GOOD_DEMO)


def test_check_database_tls_is_usable_directly():
    check_database_tls(parse_database_url(GOOD_DEMO))
    with pytest.raises(ValueError, match="without TLS"):
        check_database_tls(parse_database_url(REMOTE))


def test_errors_never_contain_the_password():
    for kwargs in (
        {"database_url": REMOTE},  # TLS refusal
        {"database_url": f"postgresql+psycopg://dataforce:{SECRET}@db.example.org:99999999/x"},
        {"database_url": "not a url " + SECRET},
        {"environment": "demo", "database_url": f"postgresql+psycopg://u:{SECRET[:3]}@h/db"},
        {"test_database_url": REMOTE},
        {"tamtam_mcp_url": f"http://u:{SECRET}@evil.example/mcp"},
    ):
        assert SECRET not in error_text(**kwargs), kwargs
        assert SECRET[:6] not in error_text(**kwargs), kwargs


def test_describe_database_target_has_no_credentials():
    assert describe_database_target(GOOD_DEMO) == "db.example.supabase.co:5432/postgres"
    shown = make(database_url=GOOD_DEMO).database_target
    assert shown == "db.example.supabase.co:5432/postgres" and "app:" not in shown
    assert describe_database_target("postgresql+psycopg:///db") == "(local socket)/db"


# --- SR3-03: environment lockdown ---------------------------------------------------------------


def test_dev_and_test_keep_the_default_dev_credentials():
    for env in ("dev", "test"):
        assert "dataforce:dataforce@" in make(environment=env).database_url.get_secret_value()


def test_demo_refuses_the_default_dev_database_url():
    message = error_text(environment="demo")
    assert "dev credentials" in message and "DATABASE_URL" in message


def test_demo_refuses_dev_credentials_even_when_given_explicitly():
    url = "postgresql+psycopg://dataforce:dataforce@db.internal:5432/dataforce?sslmode=require"
    assert "dev credentials" in error_text(environment="demo", database_url=url)


@pytest.mark.parametrize(
    "password",
    ["", "[YOUR-PASSWORD]", "<password>", "changeme", "PASSWORD", "postgres", "short", "abc1234"],
)
def test_demo_refuses_empty_placeholder_and_short_passwords(password):
    url = f"postgresql+psycopg://app:{password}@db.example.org:5432/postgres?sslmode=require"
    message = error_text(environment="demo", database_url=url)
    assert "DATABASE_URL" in message
    assert "password" in message


def test_demo_refuses_a_url_without_password():
    url = "postgresql+psycopg://app@db.example.org:5432/postgres?sslmode=require"
    assert "no password" in error_text(environment="demo", database_url=url)


def test_demo_accepts_a_real_url_with_tls():
    settings = make(environment="demo", database_url=GOOD_DEMO)
    assert settings.environment == "demo"
    assert settings.database_url.get_secret_value() == GOOD_DEMO


def test_demo_still_requires_tls_on_a_remote_host():
    assert "without TLS" in error_text(environment="demo", database_url=REMOTE)


def test_demo_does_not_check_the_test_database_credentials():
    # the test URL keeps its dev default: it is not used by a demo run
    assert make(environment="demo", database_url=GOOD_DEMO).test_database_url


def test_environment_is_read_from_the_process_environment(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "demo")
    with pytest.raises(ValidationError, match="dev credentials"):
        Settings(_env_file=None)


# --- SR3-10 / SR2-12: endpoints -----------------------------------------------------------------

ENDPOINT_FIELDS = ["tamtam_mcp_url"]


@pytest.mark.parametrize("field", ENDPOINT_FIELDS)
def test_defaults_are_https(field):
    assert getattr(make(), field).startswith("https://")


@pytest.mark.parametrize("field", ENDPOINT_FIELDS)
@pytest.mark.parametrize(
    "value",
    [
        "http://api.tamtam.ai/mcp",  # clear-text token
        "ftp://example.org/x",
        "javascript:alert(1)",
        "//example.org/x",
        "example.org/mcp",
        "https://",
        "https://user:pw@example.org/mcp",  # credentials in the URL
        "",
    ],
)
def test_endpoint_must_be_a_plain_https_url(field, value):
    assert field.upper() in error_text(**{field: value})


@pytest.mark.parametrize("field", ENDPOINT_FIELDS)
def test_http_is_allowed_for_loopback_in_dev_and_test_only(field):
    local = "http://127.0.0.1:8765/x"
    assert getattr(make(**{field: local}), field) == local
    assert getattr(make(environment="test", **{field: local}), field) == local
    message = error_text(environment="demo", database_url=GOOD_DEMO, **{field: local})
    assert "dev/test" in message


def test_https_loopback_and_remote_are_fine():
    assert make(tamtam_mcp_url="https://mcp.example.org/mcp")
    assert make(tamtam_mcp_url="https://localhost:8443")


# --- timeouts ------------------------------------------------------------------------------------


def test_db_timeout_defaults_are_sane_and_bounded():
    s = make()
    assert s.db_connect_timeout_s == 10
    assert s.db_statement_timeout_ms == 60_000 and s.db_lock_timeout_ms == 15_000
    assert s.db_disable_prepared_statements is False
    for bad in ({"db_connect_timeout_s": 0}, {"db_statement_timeout_ms": -1}):
        with pytest.raises(ValidationError):
            make(**bad)


def test_existing_tech_lead_fields_are_kept():
    s = make()
    assert s.llm_max_calls_per_run == 2000
    assert s.enrichment_max_credits_per_call == 10.0


# --- get_settings(): .env file --------------------------------------------------------------------


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """Point Settings/get_settings at a temporary .env and restore the cache afterwards."""
    path = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", path)
    monkeypatch.setitem(Settings.model_config, "env_file", path)
    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


def test_open_env_file_only_warns_in_dev(env_file, caplog):
    env_file.write_text("LLM_PROVIDER=fake\n")
    env_file.chmod(0o644)
    with caplog.at_level(logging.WARNING, logger="app.config"):
        settings = get_settings()
    assert settings.llm_provider == "fake"
    assert "readable by group/others" in caplog.text


def test_open_env_file_is_an_error_outside_dev(env_file, monkeypatch):
    env_file.write_text("LLM_PROVIDER=fake\n")
    env_file.chmod(0o640)
    monkeypatch.setenv("ENVIRONMENT", "demo")
    monkeypatch.setenv("DATABASE_URL", GOOD_DEMO)
    with pytest.raises(ConfigError, match="chmod 600"):
        get_settings()


def test_private_env_file_is_fine_outside_dev(env_file, monkeypatch, caplog):
    env_file.write_text("LLM_PROVIDER=fake\n")
    env_file.chmod(0o600)
    assert stat.S_IMODE(os.stat(env_file).st_mode) == 0o600
    monkeypatch.setenv("ENVIRONMENT", "demo")
    monkeypatch.setenv("DATABASE_URL", GOOD_DEMO)
    with caplog.at_level(logging.WARNING, logger="app.config"):
        assert get_settings().environment == "demo"
    assert "readable by group" not in caplog.text


def test_unknown_env_keys_are_reported_by_name_only(env_file, caplog):
    env_file.write_text(
        f"DATABSE_URL={SECRET}\nGEMINI_API_KEY=k\nPOSTGRES_PASSWORD=x\nTOTALLY_OTHER=1\n"
    )
    env_file.chmod(0o600)
    with caplog.at_level(logging.WARNING, logger="app.config"):
        get_settings()
    assert "unknown setting DATABSE_URL is ignored; did you mean DATABASE_URL?" in caplog.text
    assert "TOTALLY_OTHER" in caplog.text
    assert "POSTGRES_PASSWORD" not in caplog.text  # docker compose variable, not ours
    assert "GEMINI_API_KEY" not in caplog.text
    assert SECRET not in caplog.text  # values are never logged
