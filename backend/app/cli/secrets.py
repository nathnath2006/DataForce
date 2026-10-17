"""`dataforce secrets init`: create DATAFORCE_SECRET_KEY (a Fernet key) in backend/.env.

The key seals connector tokens and enriched contact values at rest. It is written to the env file
(mode 0600) and never printed.
"""

from __future__ import annotations

import os
import re
import stat
from typing import Annotated

import typer
from cryptography.fernet import Fernet
from dotenv import dotenv_values

from app import config
from app.cli._common import console, fail, make_subapp

app = make_subapp("Local secrets (the key that seals tokens and enriched contact values).")

KEY_NAME = "DATAFORCE_SECRET_KEY"


def _key_in_environment() -> bool:
    return bool(os.environ.get(KEY_NAME, "").strip())


def _key_in_file(path) -> bool:
    if not path.exists():
        return False
    return bool((dotenv_values(path).get(KEY_NAME) or "").strip())


@app.command("init")
def init(
    if_missing: Annotated[
        bool,
        typer.Option("--if-missing", help="Do nothing when a key is already set (for `make ui`)."),
    ] = False,
) -> None:
    """Generate a Fernet key and write it to backend/.env (chmod 600). Never prints the key."""
    path = config.ENV_FILE
    present = _key_in_environment() or _key_in_file(path)
    if present:
        if if_missing:
            console.print("DATAFORCE_SECRET_KEY is already set; nothing to do.")
            return
        raise fail(
            "DATAFORCE_SECRET_KEY is already set. Replacing it would make every stored token and "
            "channel unreadable; remove it from the env file by hand if you really mean to."
        )
    if path.is_symlink():
        raise fail(
            f"{path} is a symbolic link. Refusing to write through it; replace it with a regular "
            "file (or write the key there by hand)."
        )
    line = f"{KEY_NAME}={Fernet.generate_key().decode('ascii')}"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = existing.splitlines()
    empty = re.compile(rf"^\s*(?:export\s+)?{KEY_NAME}\s*=\s*(?:(['\"])\s*\1)?\s*(?:#.*)?$")
    for index, current in enumerate(lines):
        if empty.match(current):
            lines[index] = line  # replace the empty assignment instead of adding a duplicate
            break
    else:
        lines.append(line)
    _write_private(path, "\n".join(lines) + "\n")
    console.print(f"Wrote {KEY_NAME} to {path} (mode 600). The key is not shown.")


def _write_private(path, content: str) -> None:
    """Temp file in the same directory (mode 0600 from creation), then an atomic replace."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
