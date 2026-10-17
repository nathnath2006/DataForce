"""SR3-04: the integration fixtures must refuse a dangerous TEST_DATABASE_URL."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from app.config import BACKEND_DIR
from tests.conftest import TEST_DB_PROBLEM, check_test_database_url

PW = "Zq7-guard-secret"  # noqa: S105
DEV = f"postgresql+psycopg://u:{PW}@localhost:5433/dataforce"


def url(db: str, host: str = "localhost") -> str:
    return f"postgresql+psycopg://u:{PW}@{host}:5433/{db}"


def test_the_session_running_these_tests_passed_the_guard():
    assert TEST_DB_PROBLEM is None


def test_a_proper_test_database_is_accepted():
    assert check_test_database_url(url("dataforce_test"), DEV) is None
    assert check_test_database_url(url("dataforce_test", "127.0.0.1"), DEV) is None


@pytest.mark.parametrize("name", ["dataforce", "postgres", "dataforce_test_backup", "test", ""])
def test_a_name_not_ending_with_test_is_refused(name):
    reason = check_test_database_url(url(name), DEV)
    assert reason is not None and "_test" in reason


def test_the_dev_database_name_is_refused_even_when_it_ends_with_test():
    reason = check_test_database_url(url("dataforce_test"), url("dataforce_test", "db.example.org"))
    assert reason is not None and "same name" in reason


def test_a_remote_host_is_refused_unless_explicitly_allowed():
    remote = url("dataforce_test", "db.example.supabase.co")
    reason = check_test_database_url(remote, DEV)
    assert reason is not None and "ALLOW_REMOTE_TEST_DB" in reason
    assert check_test_database_url(remote, DEV, allow_remote=True) is None
    # the name rule still applies when remote is allowed
    assert check_test_database_url(url("postgres", "db.example.org"), DEV, allow_remote=True)


def test_reasons_never_contain_the_password():
    for test_url in (
        url("dataforce"),
        url("dataforce_test", "db.example.org"),
        f"not a url {PW}",
        url("dataforce_test"),
    ):
        reason = check_test_database_url(test_url, url("dataforce_test", "other"))
        assert reason is None or PW not in reason


def _pytest_subprocess(test_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in {"DATABASE_URL", "ENVIRONMENT"}}
    env["TEST_DATABASE_URL"] = test_url
    return subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_a_dev_database_as_test_url_stops_the_session_before_any_integration_test():
    result = _pytest_subprocess(url("dataforce"), "tests/db/test_session.py")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "must end with '_test'" in result.stdout + result.stderr
    assert PW not in result.stdout + result.stderr


def test_unit_tests_still_run_with_a_refused_url():
    result = _pytest_subprocess(url("dataforce"), "tests/db/test_env_example.py")
    assert result.returncode == 0, result.stdout + result.stderr
