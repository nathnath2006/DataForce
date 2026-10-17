"""backend/.env.example must list every Settings field and never contain a secret value."""

import re
from pathlib import Path

from pydantic import SecretStr

from app.config import BACKEND_DIR, Settings

ENV_EXAMPLE = Path(BACKEND_DIR) / ".env.example"
ASSIGNMENT = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=(.*)$")


def _assignments() -> dict[str, str]:
    found: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text().splitlines():
        match = ASSIGNMENT.match(line)
        if match:
            found[match.group(1)] = match.group(2).strip()
    return found


def test_every_settings_field_is_documented():
    documented = set(_assignments())
    missing = {name.upper() for name in Settings.model_fields} - documented
    assert not missing, f"missing from backend/.env.example: {sorted(missing)}"


def test_no_unknown_variables_are_documented():
    known = {name.upper() for name in Settings.model_fields}
    extra = set(_assignments()) - known
    assert not extra, f"not Settings fields (typo?): {sorted(extra)}"


def test_secret_api_keys_have_no_value():
    secret_fields = {
        name.upper()
        for name, field in Settings.model_fields.items()
        if "SecretStr" in str(field.annotation) and field.default is None
    }
    assert secret_fields >= {"GEMINI_API_KEY", "ANTHROPIC_API_KEY", "TAMTAM_MCP_TOKEN"}
    values = _assignments()
    for name in secret_fields:
        assert values[name] == "", f"{name} must be empty in .env.example"


def test_secret_defaults_are_dev_only_values():
    default = Settings.model_fields["database_url"].default
    assert isinstance(default, SecretStr)
    assert "localhost" in default.get_secret_value()
