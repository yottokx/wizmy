"""
UIセッション状態の管理。

NiceGUI の storage を使用してUI状態を管理する。
ボルトのマスターパスワードはプロセス内メモリに保持し、永続化しない。
最終アクセスから一定時間が経過したパスワードは破棄する。
"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from nicegui import app
from nicegui.storage import request_contextvar

_VAULT_PASSWORD_KEY = "vault_password"
_VAULT_PASSWORD_TTL_SECONDS = 8 * 60 * 60


@dataclass
class _VaultPasswordEntry:
    password: str
    last_access_at: float


_SESSION_VAULT_PASSWORDS: dict[str, _VaultPasswordEntry] = {}


def _now() -> float:
    return monotonic()


def _current_session_id() -> str | None:
    request = request_contextvar.get()
    if request is None:
        return None
    return request.session.get("id")


def _clear_legacy_persisted_vault_password() -> None:
    """旧バージョンが永続ストレージに残した Vault パスワードを削除する。"""
    try:
        app.storage.user.pop(_VAULT_PASSWORD_KEY, None)
    except RuntimeError:
        pass


def _clear_expired_vault_passwords(now: float | None = None) -> None:
    current = _now() if now is None else now
    expired_session_ids = [
        session_id
        for session_id, entry in _SESSION_VAULT_PASSWORDS.items()
        if current - entry.last_access_at >= _VAULT_PASSWORD_TTL_SECONDS
    ]
    for session_id in expired_session_ids:
        _SESSION_VAULT_PASSWORDS.pop(session_id, None)


def get_vault_password() -> str | None:
    _clear_legacy_persisted_vault_password()
    now = _now()
    _clear_expired_vault_passwords(now)
    session_id = _current_session_id()
    if session_id is None:
        return None
    entry = _SESSION_VAULT_PASSWORDS.get(session_id)
    if entry is None:
        return None
    entry.last_access_at = now
    return entry.password


def set_vault_password(password: str) -> None:
    _clear_legacy_persisted_vault_password()
    now = _now()
    _clear_expired_vault_passwords(now)
    session_id = _current_session_id()
    if session_id is not None:
        _SESSION_VAULT_PASSWORDS[session_id] = _VaultPasswordEntry(password=password, last_access_at=now)


def clear_vault_password() -> None:
    _clear_legacy_persisted_vault_password()
    _clear_expired_vault_passwords()
    session_id = _current_session_id()
    if session_id is not None:
        _SESSION_VAULT_PASSWORDS.pop(session_id, None)


def is_vault_unlocked() -> bool:
    return bool(get_vault_password())
