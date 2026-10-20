"""Application settings.

Every value comes from environment variables (or `backend/.env`, which is gitignored and
should be chmod 600). Secrets are `SecretStr` so they never show up in reprs or logs; read
them with `.get_secret_value()` only at the point of use (inside a provider client).

Guards enforced at load time (a bad value fails fast with a message that never echoes a
secret; `hide_input_in_errors` keeps pydantic from printing the offending input):

* `database_url` must use TLS (`sslmode=require|verify-ca|verify-full`) unless the host is
  loopback (SR3-02);
* outside `dev` / `test` (i.e. `ENVIRONMENT=demo`) the default `dataforce:dataforce` credentials and
  empty / placeholder / very short passwords are refused, and an open `.env` is an error
  instead of a warning (SR3-03, SR2-18);
* endpoints that receive a token (`tamtam_mcp_url`) must be https (http only for loopback in
  dev / test) and carry no credentials (SR3-10, SR2-12).
"""

from __future__ import annotations

import base64
import binascii
import difflib
import ipaddress
import logging
import stat
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"

log = logging.getLogger(__name__)

# Environments where the dev conveniences (default credentials, http://localhost endpoints,
# a merely-warned open .env) are acceptable. Anything else (today: "demo") is locked down.
DEV_ENVIRONMENTS = frozenset({"dev", "test"})

# libpq sslmodes that refuse a clear-text fallback. `require` encrypts without verifying the
# server certificate; `verify-full` (with the provider CA in `sslrootcert`) also stops a MITM.
TLS_SSLMODES = frozenset({"require", "verify-ca", "verify-full"})

DEV_DB_USER = "dataforce"
DEV_DB_PASSWORD = "dataforce"  # noqa: S105 - the documented docker-compose dev credential
MIN_NON_DEV_PASSWORD_LENGTH = 8

# Passwords that are templates or well-known defaults, never real secrets.
_PLACEHOLDER_PASSWORDS = frozenset(
    {
        "dataforce", "tamtam", "password", "passw0rd",
        "changeme", "change-me", "change_me", "postgres",
        "secret", "admin", "root", "test", "demo", "example", "xxx", "xxxx", "***",
        "your-password", "your_password", "yourpassword", "[your-password]", "[password]",
        "<password>", "{password}", "$password", "password123", "12345678", "123456789",
    }
)  # fmt: skip


class ConfigError(ValueError):
    """The configuration is unsafe or unusable. Messages never contain a secret value."""


# --- database URL helpers (pure, shared with tests/conftest.py and the CLI) ----------------


def parse_database_url(raw: str) -> URL:
    """SQLAlchemy URL from a string. The error never echoes the input (it holds a password)."""
    try:
        return make_url(raw)
    except Exception:  # noqa: BLE001 - make_url's messages can quote the URL
        raise ValueError(
            "not a valid database URL; expected "
            "postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME "
            "(URL-encode special characters in the password)"
        ) from None


def _as_tuple(value: str | tuple[str, ...] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return (value,) if isinstance(value, str) else tuple(value)


def database_hosts(url: URL) -> list[str]:
    """Every host libpq could connect to for this URL (host, ?host=, ?hostaddr=)."""
    hosts: list[str] = []
    if url.host:
        hosts.extend(url.host.split(","))
    for key in ("host", "hostaddr"):
        for value in _as_tuple(url.query.get(key)):
            hosts.extend(value.split(","))
    return [h.strip() for h in hosts if h.strip()]


def is_loopback_host(host: str) -> bool:
    """localhost, 127.0.0.0/8, ::1, or a unix-socket directory (a path)."""
    host = host.strip().strip("[]").rstrip(".").lower()
    if host == "localhost" or host.startswith("/"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def database_is_local(url: URL) -> bool:
    """True when every possible host is loopback / a socket (no host at all = unix socket)."""
    return all(is_loopback_host(h) for h in database_hosts(url))


def database_uses_tls(url: URL) -> bool:
    modes = _as_tuple(url.query.get("sslmode"))
    return bool(modes) and all(m in TLS_SSLMODES for m in modes)


def describe_database_target(url: str | URL) -> str:
    """`host:port/dbname` for logs and `tt` banners. Never contains the user or password."""
    parsed = parse_database_url(url) if isinstance(url, str) else url
    hosts = ",".join(database_hosts(parsed)) or "(local socket)"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{hosts}{port}/{parsed.database or ''}"


def check_database_tls(url: URL, *, setting: str = "DATABASE_URL") -> None:
    """Refuse a non-loopback host unless the URL demands TLS (libpq's default sslmode=prefer
    silently falls back to clear text, which would expose the password to a network attacker)."""
    if not url.drivername.startswith("postgres") or database_is_local(url):
        return
    if not database_uses_tls(url):
        raise ValueError(
            f"{setting} points at a remote host ({describe_database_target(url)}) without TLS. "
            "Add ?sslmode=require (or sslmode=verify-full&sslrootcert=/path/to/ca.crt) to the "
            "URL; libpq's default would silently fall back to clear text."
        )


def check_non_dev_credentials(url: URL, *, setting: str = "DATABASE_URL") -> None:
    """The lockdown applied when ENVIRONMENT is not dev/test."""
    password = url.password or ""
    if url.username == DEV_DB_USER and password == DEV_DB_PASSWORD:
        raise ValueError(
            f"{setting} still uses the dev credentials (dataforce:dataforce). Set a real "
            f"{setting} (and change the database password) before running with "
            "ENVIRONMENT != dev."
        )
    lowered = password.strip().lower()
    if not lowered:
        raise ValueError(f"{setting} has no password; a password is required outside dev.")
    templated = lowered[0] in "[<{$" or "your-password" in lowered or "your_password" in lowered
    if lowered in _PLACEHOLDER_PASSWORDS or templated:
        raise ValueError(
            f"{setting} contains a placeholder / well-known password. Use the real password "
            "(URL-encoded)."
        )
    if len(password) < MIN_NON_DEV_PASSWORD_LENGTH:
        raise ValueError(
            f"{setting} has a password shorter than {MIN_NON_DEV_PASSWORD_LENGTH} characters; "
            "use a long random one outside dev."
        )


def check_endpoint_url(name: str, value: str, environment: str) -> str:
    """https only (http is tolerated for loopback in dev/test so local stubs work), no embedded
    credentials. The error never echoes the value."""
    parts = urlsplit(value.strip())
    host = parts.hostname or ""
    if parts.username or parts.password:
        raise ValueError(f"{name} must not contain credentials in the URL")
    if parts.scheme == "https" and host:
        return value
    if parts.scheme == "http" and host and is_loopback_host(host):
        if environment in DEV_ENVIRONMENTS:
            return value
        raise ValueError(f"{name}: http:// is only accepted in dev/test; use https://")
    raise ValueError(
        f"{name} must be an https:// URL (http:// is only accepted for localhost in dev/test)"
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        # A failed validation must never print the raw input (it can be a DATABASE_URL).
        hide_input_in_errors=True,
    )

    # dev/test: local conveniences. demo (any non-dev/test value): the lockdown described in the
    # module docstring is enforced.
    environment: Literal["dev", "test", "demo"] = "dev"

    # --- database -------------------------------------------------------------------------
    # Local dev default matches docker-compose.yml. Supabase: paste its connection string,
    # in the form postgresql+psycopg://USER:PASSWORD@HOST:PORT/DB?sslmode=require
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://dataforce:dataforce@localhost:5433/dataforce"
    )
    test_database_url: SecretStr = SecretStr(
        "postgresql+psycopg://dataforce:dataforce@localhost:5433/dataforce_test"
    )
    # Postgres does not know the hosting cap (Supabase free = 500 MB); it is a config value.
    db_quota_mb: int = Field(default=500, ge=1)  # hosting storage cap; the admin view shows usage
    # A stalled pooler / dead network must not hang a command forever. Statement and lock
    # timeouts are applied per transaction (SET LOCAL) so they also work behind a transaction
    # pooler; 0 disables. Migrations (alembic) only use the connect timeout.
    db_connect_timeout_s: int = Field(default=10, ge=1, le=300)
    db_statement_timeout_ms: int = Field(default=60_000, ge=0)
    db_lock_timeout_ms: int = Field(default=15_000, ge=0)
    # psycopg3 prepares statements after a few executions; a transaction pooler (Supabase
    # port 6543) breaks that. Also switched on automatically for port 6543.
    db_disable_prepared_statements: bool = False

    # --- LLM / embeddings -----------------------------------------------------------------
    llm_provider: Literal["gemini", "anthropic", "fake"] = "gemini"
    embedding_provider: Literal["gemini", "fake"] = "gemini"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash"
    gemini_embedding_model: str = "gemini-embedding-001"
    # Must equal app.db.models.EMBEDDING_DIM (the pgvector column size). Changing it = migration.
    embedding_dim: int = 768
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-haiku-5-5"
    llm_timeout_s: float = Field(default=60.0, gt=0, le=600, allow_inf_nan=False)
    llm_max_concurrency: int = 4
    # Spend ceiling: a run stops calling the LLM past this many calls.
    llm_max_calls_per_run: int = 2000

    # --- stats engine: "not verified" gates (decided 2026-10-17, all configurable) ----------
    stats_confidence: float = Field(default=0.95, gt=0.5, lt=1.0, allow_inf_nan=False)
    # Benjamini-Hochberg false discovery rate for segment scans (many comparisons at once).
    stats_fdr_alpha: float = Field(default=0.05, gt=0.0, lt=0.5, allow_inf_nan=False)
    gate_min_n: int = Field(default=30, ge=1)  # deals in the group
    gate_min_wins: int = Field(default=10, ge=0)  # for a win rate
    gate_min_losses: int = Field(default=10, ge=0)
    # Rates, in percentage points.
    gate_max_ci_halfwidth_pts: float = Field(default=15.0, gt=0, le=50, allow_inf_nan=False)
    # Medians / means (cycle length, deal size): CI half-width relative to the estimate.
    gate_max_ci_rel_halfwidth: float = Field(default=0.30, gt=0, le=1, allow_inf_nan=False)
    stats_bootstrap_resamples: int = Field(default=2000, ge=200)
    stats_random_seed: int = 42

    # --- synthetic demo data --------------------------------------------------------------
    # The workspace behind the public "Try the demo" button (it must exist and be a test
    # workspace). `dataforce demo reset` rebuilds it every night.
    demo_workspace: str = Field(default="test-data", pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")

    # --- TamTam connector / enrichment (paid lookups only on explicit click) ----------------
    enrichment_provider: Literal["tamtam_mcp", "fake", "none"] = "none"
    tamtam_mcp_url: str = "https://api.tamtam.ai/mcp"
    # Legacy / headless path: a pasted access token. The UI's "Connect TamTam" (OAuth, stored
    # sealed in the database per workspace) is the normal way and takes precedence.
    tamtam_mcp_token: SecretStr | None = None
    # Hard ceiling per enrichment call; anything above (estimated or server-reported) is refused.
    enrichment_max_credits_per_call: float = Field(default=10.0, gt=0, le=1000, allow_inf_nan=False)
    # OAuth authorization servers we accept for the TamTam MCP resource (exact origins). The
    # discovered server must be one of these, so a tampered metadata document cannot send the
    # browser, or the authorization code, anywhere else.
    tamtam_oauth_allowed_issuers: list[str] = ["https://api.tamtam.ai"]

    # --- local web UI (M1b: loopback only, no login until M3) -------------------------------
    # Fernet key (urlsafe base64, 32 bytes) that seals connector tokens and enriched contact
    # values at rest. `dataforce secrets init` writes one into backend/.env (chmod 600).
    dataforce_secret_key: SecretStr | None = None
    ui_host: str = "127.0.0.1"
    ui_port: int = Field(default=8800, ge=1024, le=65535)
    # Origins allowed to send state-changing requests (POST/PATCH/PUT/DELETE). The Vite dev
    # server (5173) is included for `make ui-dev`.
    ui_allowed_origins: list[str] = [
        "http://127.0.0.1:8800",
        "http://localhost:8800",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    # Hosted mode (docs/HOSTED-MODE-CONTRACT.md): the one switch. Empty = local mode. Set to the
    # public https origin (e.g. https://dataforce-abc123-ew.a.run.app) = hosted mode.
    public_origin: str = ""
    # Email (M6): Gmail over SMTP with an App Password, STARTTLS required. Without a username and
    # password nothing is sent and the reset link goes to the server log (local dev).
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr | None = None
    mail_from: str = ""  # empty = SMTP_USERNAME
    mail_from_name: str = "DataForce"
    # Invitation emails: per workspace and per sender per day, and active join tokens per workspace.
    invite_emails_per_workspace_per_day: int = Field(default=20, ge=0, le=1000)
    invite_emails_per_user_per_day: int = Field(default=10, ge=0, le=1000)
    join_tokens_max_active: int = Field(default=50, ge=1, le=1000)
    # Kill switch: false closes public sign-up; /api/auth/join (signed in) is unaffected.
    signup_enabled: bool = True
    # Extra Host header values accepted in hosted mode (e.g. a custom domain).
    allowed_hosts: list[str] = []
    # Hosted only: take the client address from X-Forwarded-For as appended by the platform's
    # front end. The LAST `trust_proxy_hops` entries are written by trusted proxies; anything
    # before them is client-controlled and ignored (Cloud Run: 1).
    trust_proxy: bool = False
    trust_proxy_hops: int = Field(default=1, ge=1, le=5)
    # Built frontend served at / (empty or missing = API only).
    ui_dist_dir: Path = BACKEND_DIR.parent / "frontend" / "dist"

    # --- M2a: analysis flows, company registry, AI assistant --------------------------------
    upload_max_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    flow_max_rows: int = Field(default=200_000, ge=1_000, le=5_000_000)  # per dataset / block
    flow_run_timeout_s: float = Field(default=60.0, gt=0, le=600, allow_inf_nan=False)
    # External database connections: query timeout (also sent as statement_timeout).
    data_connection_timeout_s: float = Field(default=30.0, gt=0, le=300, allow_inf_nan=False)
    # Public French company registry (no key). Searched only when the user asks.
    registry_url: str = "https://recherche-entreprises.api.gouv.fr"
    # Flow runs executing at the same time (a timed-out run cannot be killed, only told to stop).
    flow_max_concurrent_runs: int = Field(default=2, ge=1, le=16)
    # AI assistant: answer length, how much account context is sent, and a cost guard.
    assistant_max_output_tokens: int = Field(default=800, ge=64, le=4096)
    assistant_max_context_chars: int = Field(default=40_000, ge=2_000, le=400_000)
    assistant_max_asks_per_hour: int = Field(default=60, ge=1, le=10_000)  # per workspace

    # --- M2b: titles, transcripts, themes ---------------------------------------------------
    # AI title classifications per normalisation run (unknown titles only, then cached).
    titles_max_llm_calls_per_run: int = Field(default=200, ge=0, le=5_000)
    titles_max_llm_calls_per_day: int = Field(default=1_000, ge=0, le=50_000)  # per workspace
    # Opt-in AI pass over candidate meeting sentences (docs/ORG-AI-CONTRACT.md): structured calls.
    org_ai_max_calls_per_run: int = Field(default=50, ge=0, le=5_000)
    org_ai_max_calls_per_day: int = Field(default=500, ge=0, le=50_000)  # per workspace
    transcript_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    transcript_max_pages: int = Field(default=300, ge=1, le=2_000)  # PDF
    transcript_max_chars: int = Field(default=1_000_000, ge=1_000, le=10_000_000)
    themes_default_k: int = Field(default=12, ge=2, le=30)  # v2: formulas need topics too
    # Opt-in GenAI on a deal or account (summary, suggested tasks): text budget and daily cap.
    genai_max_source_chars: int = Field(default=20_000, ge=1_000, le=200_000)
    genai_max_calls_per_day: int = Field(default=200, ge=0, le=50_000)  # per workspace

    # --- validators -----------------------------------------------------------------------
    # Field validators (not a model validator) on purpose: they see the already-wrapped
    # SecretStr, and `environment` is declared first so `info.data` has it.

    @field_validator("database_url", mode="after")
    @classmethod
    def _check_database_url(cls, value: SecretStr, info: ValidationInfo) -> SecretStr:
        url = parse_database_url(value.get_secret_value())
        check_database_tls(url, setting="DATABASE_URL")
        if info.data.get("environment", "dev") not in DEV_ENVIRONMENTS:
            check_non_dev_credentials(url, setting="DATABASE_URL")
        return value

    @field_validator("test_database_url", mode="after")
    @classmethod
    def _check_test_database_url(cls, value: SecretStr) -> SecretStr:
        # Dev credentials are fine here (that is what docker-compose creates); TLS is not
        # optional for a remote host (tests/conftest.py also refuses remote hosts by default).
        url = parse_database_url(value.get_secret_value())
        check_database_tls(url, setting="TEST_DATABASE_URL")
        return value

    # --- mailbox (M4 phase 2): Gmail / Outlook, read-only ------------------------------------
    # OAuth clients the PO registers (docs/MAILBOX-SETUP.md). Entered in Settings (sealed in the
    # database) they take precedence; these are the headless fallback.
    mailbox_google_client_id: str | None = None
    mailbox_google_client_secret: SecretStr | None = None
    mailbox_microsoft_client_id: str | None = None
    mailbox_microsoft_client_secret: SecretStr | None = None
    mailbox_microsoft_tenant: str = Field(default="common", pattern=r"^[A-Za-z0-9.-]{1,64}$")
    mailbox_lookback_days: int = Field(default=30, ge=1, le=365)
    mailbox_max_messages: int = Field(default=500, ge=1, le=5000)
    mailbox_suggest_threshold: int = Field(default=40, ge=1, le=100)

    @field_validator("tamtam_mcp_url", "registry_url", mode="after")
    @classmethod
    def _check_endpoint(cls, value: str, info: ValidationInfo) -> str:
        return check_endpoint_url(
            (info.field_name or "url").upper(), value, info.data.get("environment", "dev")
        )

    @field_validator("dataforce_secret_key", mode="after")
    @classmethod
    def _check_secret_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return None
        try:
            raw = base64.urlsafe_b64decode(value.get_secret_value().strip().encode("ascii"))
        except (binascii.Error, UnicodeEncodeError, ValueError):
            raw = b""
        if len(raw) != 32:
            raise ValueError(
                "DATAFORCE_SECRET_KEY must be a Fernet key (urlsafe base64 of 32 bytes); "
                "generate one with: dataforce secrets init"
            )
        return value

    @field_validator("ui_host", mode="after")
    @classmethod
    def _check_ui_host(cls, value: str) -> str:
        # No login before M3: the UI must never listen on a network interface.
        if not is_loopback_host(value) or value.startswith("/"):
            raise ValueError("UI_HOST must be a loopback address (127.0.0.1, ::1 or localhost)")
        return value

    @field_validator("public_origin", mode="after")
    @classmethod
    def _check_public_origin(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        parts = urlsplit(value)
        if parts.scheme != "https":
            raise ValueError("PUBLIC_ORIGIN must be an https:// origin (even on localhost)")
        if (
            not parts.hostname
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
            or parts.username is not None
            or parts.password is not None
        ):
            raise ValueError("PUBLIC_ORIGIN must be a bare origin (https://host[:port])")
        return f"https://{parts.netloc}".lower()

    @field_validator("allowed_hosts", mode="after")
    @classmethod
    def _check_allowed_hosts(cls, value: list[str]) -> list[str]:
        out = []
        for host in value:
            host = host.strip().lower()
            if not host or any(c in host for c in "/?#@ "):
                raise ValueError("ALLOWED_HOSTS: each entry must be a bare host[:port]")
            out.append(host)
        return out

    @field_validator("tamtam_oauth_allowed_issuers", "ui_allowed_origins", mode="after")
    @classmethod
    def _check_origins(cls, value: list[str], info: ValidationInfo) -> list[str]:
        name = (info.field_name or "origins").upper()
        out: list[str] = []
        for origin in value:
            parts = urlsplit(origin.strip())
            if parts.path not in ("", "/") or parts.query or parts.fragment or parts.username:
                raise ValueError(f"{name}: each entry must be a bare origin (scheme://host[:port])")
            local_ui = (
                info.field_name == "ui_allowed_origins"
                and parts.scheme == "http"
                and is_loopback_host(parts.hostname or "")
            )
            if not local_ui:  # a local UI origin is http by nature; anything else is https
                check_endpoint_url(name, origin.strip(), info.data.get("environment", "dev"))
            out.append(f"{parts.scheme}://{parts.netloc}".lower())
        return out

    @property
    def database_target(self) -> str:
        """`host:port/db` of the configured database (no credentials), for banners and logs."""
        return describe_database_target(self.database_url.get_secret_value())


def is_hosted(settings: Settings) -> bool:
    """Hosted mode is on exactly when PUBLIC_ORIGIN is set, never inferred from anything else."""
    return bool(settings.public_origin)


def ui_origin(settings: Settings) -> str:
    """Where links in emails and logs point: the public origin when hosted, else the local UI."""
    return settings.public_origin or f"http://{settings.ui_host}:{settings.ui_port}"


def effective_origins(settings: Settings) -> list[str]:
    """Origins allowed to send state-changing requests: only the public origin when hosted."""
    return [settings.public_origin] if is_hosted(settings) else list(settings.ui_allowed_origins)


def _env_file_is_open() -> bool:
    try:
        mode = ENV_FILE.stat().st_mode
    except FileNotFoundError:
        return False
    return bool(mode & (stat.S_IRWXG | stat.S_IRWXO))


def _warn_unknown_env_keys() -> None:
    """`extra="ignore"` hides typos (a misspelt DATABASE_URL silently falls back to the local dev
    database). Every key in our own .env that is not a Settings field is reported by name only."""
    if not ENV_FILE.exists():
        return
    known = sorted(name.upper() for name in Settings.model_fields)
    try:
        keys = list(dotenv_values(ENV_FILE))
    except Exception:  # noqa: BLE001 - an unreadable .env is reported by Settings() itself
        return
    for key in keys:
        upper = key.upper()
        if upper in known or upper.startswith("POSTGRES_"):  # POSTGRES_* belong to docker compose
            continue
        close = difflib.get_close_matches(upper, known, n=1, cutoff=0.7)
        hint = f"; did you mean {close[0]}?" if close else ""
        log.warning("%s: unknown setting %s is ignored%s", ENV_FILE, key, hint)


@lru_cache
def get_settings() -> Settings:
    _warn_unknown_env_keys()
    settings = Settings()
    if _env_file_is_open():
        if settings.environment in DEV_ENVIRONMENTS:
            log.warning("%s is readable by group/others; run: chmod 600 %s", ENV_FILE, ENV_FILE)
        else:
            raise ConfigError(
                f"{ENV_FILE} is readable by group/others and ENVIRONMENT={settings.environment}; "
                f"run: chmod 600 {ENV_FILE}"
            )
    return settings
