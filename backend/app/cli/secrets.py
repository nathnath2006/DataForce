"""`dataforce secrets init`: create DATAFORCE_SECRET_KEY (a Fernet key) in backend/.env.

The key seals connector tokens and enriched contact values at rest. It is written to the env file
(mode 0600) and never printed.
"""

from __future__ import annotations

import os
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
    """Generate a Fernet key and append it to backend/.env (chmod 600). Never prints the key."""
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
    line = f"{KEY_NAME}={Fernet.generate_key().decode('ascii')}\n"
    prefix = ""
    if path.exists() and path.stat().st_size > 0:
        with path.open("rb") as fh:
            fh.seek(-1, os.SEEK_END)
            prefix = "" if fh.read(1) == b"\n" else "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(prefix + line)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    console.print(f"Wrote {KEY_NAME} to {path} (mode 600). The key is not shown.")
