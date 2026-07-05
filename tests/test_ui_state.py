from __future__ import annotations

import pytest

from src.ui import state


@pytest.fixture(autouse=True)
def clean_vault_password_state(monkeypatch: pytest.MonkeyPatch):
    state._SESSION_VAULT_PASSWORDS.clear()
    monkeypatch.setattr(state, "_clear_legacy_persisted_vault_password", lambda: None)
    yield
    state._SESSION_VAULT_PASSWORDS.clear()


def test_vault_password_expires_after_inactivity(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 1000.0
    monkeypatch.setattr(state, "_now", lambda: now)
    monkeypatch.setattr(state, "_current_session_id", lambda: "session-a")

    state.set_vault_password("secret")

    now += state._VAULT_PASSWORD_TTL_SECONDS

    assert state.get_vault_password() is None
    assert state._SESSION_VAULT_PASSWORDS == {}


def test_vault_password_access_extends_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 1000.0
    monkeypatch.setattr(state, "_now", lambda: now)
    monkeypatch.setattr(state, "_current_session_id", lambda: "session-a")

    state.set_vault_password("secret")

    now += state._VAULT_PASSWORD_TTL_SECONDS - 1
    assert state.get_vault_password() == "secret"

    now += 2

    assert state.get_vault_password() == "secret"
