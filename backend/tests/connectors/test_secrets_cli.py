"""`dataforce secrets init`: the real backend/.env is never touched (ENV_FILE is redirected)."""

from __future__ import annotations

import os
import stat

import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values
from typer.testing import CliRunner

from app import config
from app.cli import app

runner = CliRunner()
KEY = "DATAFORCE_SECRET_KEY"


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", path)
    monkeypatch.delenv(KEY, raising=False)
    return path


def mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_creates_the_file_with_a_valid_key_and_mode_600_and_never_prints_it(env_file):
    result = runner.invoke(app, ["secrets", "init"])
    assert result.exit_code == 0, result.output
    key = dotenv_values(env_file)[KEY]
    Fernet(key.encode())  # a valid Fernet key
    assert mode(env_file) == 0o600
    assert key not in result.output and key not in (result.stderr or "")


def test_appends_to_an_existing_file_and_tightens_its_mode(env_file):
    env_file.write_text("DATABASE_URL=postgresql://x\nFOO=bar")  # no trailing newline
    env_file.chmod(0o644)
    assert runner.invoke(app, ["secrets", "init"]).exit_code == 0
    values = dotenv_values(env_file)
    assert values["FOO"] == "bar" and values["DATABASE_URL"] == "postgresql://x" and values[KEY]
    assert mode(env_file) == 0o600


def test_refuses_to_overwrite_an_existing_key(env_file):
    env_file.write_text(f"{KEY}=existing-value\n")
    result = runner.invoke(app, ["secrets", "init"])
    assert result.exit_code == 1
    assert env_file.read_text() == f"{KEY}=existing-value\n"
    assert "existing-value" not in result.output


def test_if_missing_is_a_no_op_when_the_file_has_a_key(env_file):
    env_file.write_text(f"{KEY}=existing-value\n")
    result = runner.invoke(app, ["secrets", "init", "--if-missing"])
    assert result.exit_code == 0 and env_file.read_text() == f"{KEY}=existing-value\n"


def test_if_missing_is_a_no_op_when_the_environment_has_a_key(env_file, monkeypatch):
    monkeypatch.setenv(KEY, Fernet.generate_key().decode())
    result = runner.invoke(app, ["secrets", "init", "--if-missing"])
    assert result.exit_code == 0 and not env_file.exists()


def test_environment_key_blocks_a_plain_init(env_file, monkeypatch):
    monkeypatch.setenv(KEY, Fernet.generate_key().decode())
    assert runner.invoke(app, ["secrets", "init"]).exit_code == 1
    assert not env_file.exists()


def test_if_missing_writes_when_absent_and_is_idempotent(env_file):
    assert runner.invoke(app, ["secrets", "init", "--if-missing"]).exit_code == 0
    first = env_file.read_text()
    assert runner.invoke(app, ["secrets", "init", "--if-missing"]).exit_code == 0
    assert env_file.read_text() == first and first.count(KEY) == 1


def test_an_empty_key_line_counts_as_missing(env_file):
    env_file.write_text(f"{KEY}=\n")
    assert runner.invoke(app, ["secrets", "init"]).exit_code == 0
    assert dotenv_values(env_file)[KEY]


def test_refuses_a_symlinked_env_file(tmp_path, monkeypatch):
    target = tmp_path / "real"
    target.write_text("A=1\n")
    link = tmp_path / ".env"
    link.symlink_to(target)
    monkeypatch.setattr(config, "ENV_FILE", link)
    monkeypatch.delenv(KEY, raising=False)
    result = runner.invoke(app, ["secrets", "init"])
    assert result.exit_code != 0
    assert "symbolic link" in (result.output + (result.stderr or ""))
    assert target.read_text() == "A=1\n" and link.is_symlink()


@pytest.mark.parametrize(
    "empty", ["DATAFORCE_SECRET_KEY=", 'DATAFORCE_SECRET_KEY=""', "DATAFORCE_SECRET_KEY= "]
)
def test_an_empty_key_line_is_replaced_not_duplicated(env_file, empty):
    env_file.write_text(f"A=1\n{empty}\nB=2\n")
    assert runner.invoke(app, ["secrets", "init"]).exit_code == 0
    text = env_file.read_text()
    assert text.count(KEY) == 1
    values = dotenv_values(env_file)
    Fernet(values[KEY].encode())
    assert values["A"] == "1" and values["B"] == "2"
    assert mode(env_file) == 0o600


def test_the_write_is_atomic_and_leaves_no_temp_file(env_file):
    env_file.write_text("A=1\n")
    env_file.chmod(0o644)
    inode = env_file.stat().st_ino
    assert runner.invoke(app, ["secrets", "init"]).exit_code == 0
    assert env_file.stat().st_ino != inode  # replaced via os.replace, not edited in place
    assert [p.name for p in env_file.parent.iterdir()] == [".env"]
    assert mode(env_file) == 0o600
