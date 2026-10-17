from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.connectors.crypto import UnsealError, key_configured, seal, unseal
from app.enrichment.errors import EnrichmentConfigError


def test_round_trip_and_the_ciphertext_hides_the_plaintext(settings):
    sealed = seal("jane@acme.example", settings)
    assert "jane" not in sealed and unseal(sealed, settings) == "jane@acme.example"
    assert seal("jane@acme.example", settings) != sealed  # random IV


def test_missing_key_raises_config_error_with_the_hint():
    bare = Settings(_env_file=None, environment="test")
    assert not key_configured(bare)
    for call in (lambda: seal("x", bare), lambda: unseal("x", bare)):
        with pytest.raises(EnrichmentConfigError, match="dataforce secrets init"):
            call()


def test_a_rotated_key_cannot_open_old_data(settings):
    sealed = seal("secret-value", settings)
    other = Settings(
        _env_file=None, environment="test", dataforce_secret_key=Fernet.generate_key().decode()
    )
    with pytest.raises(UnsealError) as exc:
        unseal(sealed, other)
    assert "secret-value" not in str(exc.value) and sealed not in str(exc.value)


def test_garbage_ciphertext_is_an_unseal_error(settings):
    with pytest.raises(UnsealError):
        unseal("not-fernet", settings)
