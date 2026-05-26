"""
UIセッション状態の管理。

NiceGUI の storage を使用してUI状態を管理する。
ボルトのマスターパスワードはプロセス内メモリに保持し、永続化しない。
"""

from __future__ import annotations

from nicegui import app
from nicegui.storage import request_contextvar

_VAULT_PASSWORD_KEY = "vault_password"
_ACTIVE_GENERATION_KEY = "active_generation_id"
_SESSION_VAULT_PASSWORDS: dict[str, str] = {}


def _current_session_id() -> str | None:
    request = request_contextvar.get()
    if request is None:
        return None
    return request.session.get("id")


def _clear_legacy_persisted_vault_password() -> None:
    """Remove vault passwords that older versions stored persistently."""
    try:
        app.storage.user.pop(_VAULT_PASSWORD_KEY, None)
    except RuntimeError:
        pass


def get_vault_password() -> str | None:
    _clear_legacy_persisted_vault_password()
    session_id = _current_session_id()
    if session_id is None:
        return None
    return _SESSION_VAULT_PASSWORDS.get(session_id)


def set_vault_password(password: str) -> None:
    _clear_legacy_persisted_vault_password()
    session_id = _current_session_id()
    if session_id is not None:
        _SESSION_VAULT_PASSWORDS[session_id] = password


def clear_vault_password() -> None:
    _clear_legacy_persisted_vault_password()
    session_id = _current_session_id()
    if session_id is not None:
        _SESSION_VAULT_PASSWORDS.pop(session_id, None)


def is_vault_unlocked() -> bool:
    return bool(get_vault_password())


def get_selected_generation_profile_id() -> str:
    return app.storage.user.get("selected_generation_profile_id", "")


def set_selected_generation_profile_id(profile_id: str) -> None:
    app.storage.user["selected_generation_profile_id"] = profile_id


def get_active_generation_id() -> str:
    return app.storage.user.get(_ACTIVE_GENERATION_KEY, "")


def set_active_generation_id(generation_id: str) -> None:
    app.storage.user[_ACTIVE_GENERATION_KEY] = generation_id


def clear_active_generation_id(generation_id: str | None = None) -> None:
    if generation_id and app.storage.user.get(_ACTIVE_GENERATION_KEY) != generation_id:
        return
    app.storage.user.pop(_ACTIVE_GENERATION_KEY, None)
