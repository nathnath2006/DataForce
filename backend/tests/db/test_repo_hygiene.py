"""SR3-07 / SR2-18 (.gitignore) and SR3-08 (supply chain) checks on repository files."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import BACKEND_DIR

REPO = Path(BACKEND_DIR).parent

MUST_BE_IGNORED = [
    ".env",
    "backend/.env",
    ".env.local",
    "backend/.env.production",
    "backend/.env.demo",
    "backend/.env.test",
    "backend/.env.dev",
    "backend/.env.backup",
    ".envrc",
    "backend/.envrc",
    "creds.pem",
    "deploy/server.key",
    "cert.p12",
    "backup.dump",
    "backups/dataforce.sql",
    "db_backup.sql.gz",
    "service-account.json",
    ".claude/settings.local.json",
    "reports/eval_1.md",
    "backend/.venv/bin/python",
]
MUST_STAY_TRACKABLE = [
    ".env.example",
    "backend/.env.example",
    "docker/postgres/init/01-init.sql",  # a *.sql rule would be a mistake
    "backend/alembic/versions/0002_lockdown.py",
    "docs/security/FIXES-C.md",
    "backend/requirements.lock",
    "backend/requirements-dev.lock",
    "README.md",
]


def _check_ignore(path: str) -> bool:
    """True when git ignores `path` (read-only: `git check-ignore` changes nothing)."""
    result = subprocess.run(  # noqa: S603 - fixed argv
        ["git", "check-ignore", "-q", "--no-index", path],  # noqa: S607
        cwd=REPO,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


needs_git = pytest.mark.skipif(
    shutil.which("git") is None or not (REPO / ".git").exists(),
    reason="needs git and a git checkout",
)


@needs_git
@pytest.mark.parametrize("path", MUST_BE_IGNORED)
def test_secret_and_backup_files_are_gitignored(path):
    assert _check_ignore(path), f"{path} is NOT ignored by .gitignore"


@needs_git
@pytest.mark.parametrize("path", MUST_STAY_TRACKABLE)
def test_template_and_source_files_are_not_ignored(path):
    assert not _check_ignore(path), f"{path} is ignored but must stay committable"


# --- supply chain ---------------------------------------------------------------------------

RUNTIME_LOCK = BACKEND_DIR / "requirements.lock"
DEV_LOCK = BACKEND_DIR / "requirements-dev.lock"
DEV_ONLY = {"pytest", "pytest-asyncio", "respx", "ruff", "mypy", "types-pyyaml", "pip-tools"}
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\;]+)", re.MULTILINE)


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pins(path: Path) -> dict[str, str]:
    return {_norm(m.group(1)): m.group(2) for m in PIN.finditer(path.read_text())}


def _blocks(path: Path) -> list[str]:
    """One text block per pinned requirement (the pin line plus its --hash continuation lines)."""
    text = path.read_text()
    return [b for b in re.split(r"\n(?=[A-Za-z0-9])", text) if PIN.match(b.strip())]


@pytest.mark.parametrize("lock", [RUNTIME_LOCK, DEV_LOCK], ids=lambda p: p.name)
def test_every_locked_package_is_pinned_and_hashed(lock):
    blocks = _blocks(lock)
    assert len(blocks) > 40
    for block in blocks:
        assert "--hash=sha256:" in block, f"no hash for {block.splitlines()[0]}"
    assert "--generate-hashes" in lock.read_text()  # header records how it was generated


def test_runtime_lock_has_no_dev_tools_and_dev_lock_is_a_superset():
    runtime, dev = _pins(RUNTIME_LOCK), _pins(DEV_LOCK)
    assert not DEV_ONLY & set(runtime), sorted(DEV_ONLY & set(runtime))
    assert DEV_ONLY <= set(dev)
    assert set(runtime) <= set(dev)
    assert {n: v for n, v in runtime.items() if dev[n] != v} == {}, "locks disagree on a version"


def test_every_declared_dependency_is_locked():
    pyproject = (BACKEND_DIR / "pyproject.toml").read_text()
    deps = re.search(r"^dependencies = \[(.*?)^\]", pyproject, re.S | re.M).group(1)
    names = {_norm(m) for m in re.findall(r'^\s*"([A-Za-z0-9._-]+)', deps, re.M)}
    assert names and names <= set(_pins(RUNTIME_LOCK)), names - set(_pins(RUNTIME_LOCK))


def test_pip_tools_is_a_dev_dependency():
    assert '"pip-tools' in (BACKEND_DIR / "pyproject.toml").read_text()


def test_database_image_is_pinned_by_digest():
    compose = (REPO / "docker-compose.yml").read_text()
    images = re.findall(r"^\s*image:\s*(\S+)", compose, re.M)
    assert images
    for image in images:
        assert re.search(r"@sha256:[0-9a-f]{64}$", image), f"{image} is not pinned by digest"


def test_readme_installs_from_the_hashed_lock():
    readme = (REPO / "README.md").read_text()
    assert "pip install --require-hashes -r requirements.lock" in readme
    assert "pip install --no-deps -e ." in readme
