"""
APIキーの暗号化保管庫。

PBKDF2HMAC + Fernet による暗号化でAPIキーを安全に保持する。
マスターパスワードはメモリ外に保持しないこと。
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_VAULT_VERIFIER_PLAINTEXT = "WIZMY_VAULT_OK"
_LEGACY_VAULT_VERIFIER_PLAINTEXT = "CHARAPP" + "_VAULT_OK"


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _encrypt(plain: str, password: str, salt: bytes) -> str:
    return Fernet(_derive_key(password, salt)).encrypt(plain.encode()).decode()


def _decrypt(encrypted: str, password: str, salt: bytes) -> str | None:
    try:
        return Fernet(_derive_key(password, salt)).decrypt(encrypted.encode()).decode()
    except (InvalidToken, Exception):
        return None


@dataclass
class VaultData:
    """ファイルに保存されるボルトのデータ構造。"""

    salt_b64: str = ""
    verifier: str = ""
    keys: dict[str, str] = field(default_factory=dict)

    def is_setup(self) -> bool:
        return bool(self.salt_b64 and self.verifier)

    def to_dict(self) -> dict:
        return {
            "vault_salt": self.salt_b64,
            "vault_verifier": self.verifier,
            "vault_keys": self.keys,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VaultData":
        return cls(
            salt_b64=d.get("vault_salt", ""),
            verifier=d.get("vault_verifier", ""),
            keys=d.get("vault_keys", {}),
        )


class KeyVault:
    """APIキーの暗号化保管庫。"""

    def __init__(self, vault_data: VaultData) -> None:
        self._data = vault_data

    @property
    def data(self) -> VaultData:
        return self._data

    def is_setup(self) -> bool:
        return self._data.is_setup()

    def verify_password(self, password: str) -> bool:
        if not self._data.is_setup():
            return False
        salt = base64.b64decode(self._data.salt_b64)
        decrypted = _decrypt(self._data.verifier, password, salt)
        return decrypted in {_VAULT_VERIFIER_PLAINTEXT, _LEGACY_VAULT_VERIFIER_PLAINTEXT}

    def setup(self, password: str, carry_keys: dict[str, str] | None = None) -> None:
        """マスターパスワードを新規設定する（既存キーは再暗号化して引き継ぐ）。"""
        salt = os.urandom(16)
        salt_b64 = base64.b64encode(salt).decode()
        self._data.salt_b64 = salt_b64
        self._data.verifier = _encrypt(_VAULT_VERIFIER_PLAINTEXT, password, salt)
        self._data.keys = {ep_id: _encrypt(k, password, salt) for ep_id, k in (carry_keys or {}).items()}

    def save_key(self, endpoint_id: str, api_key: str, password: str) -> None:
        if not self._data.is_setup():
            raise RuntimeError("ボルトが未セットアップです。")
        salt = base64.b64decode(self._data.salt_b64)
        self._data.keys[endpoint_id] = _encrypt(api_key, password, salt)

    def has_key(self, endpoint_id: str) -> bool:
        """指定エンドポイントに暗号化済みAPIキーが保存されているかを返す。"""
        return endpoint_id in self._data.keys

    def delete_key(self, endpoint_id: str) -> None:
        self._data.keys.pop(endpoint_id, None)

    def load_keys(self, password: str) -> dict[str, str]:
        """復号したAPIキーの辞書を返す。復号できないキーは除外する。"""
        if not self._data.is_setup():
            return {}
        salt = base64.b64decode(self._data.salt_b64)
        result: dict[str, str] = {}
        for ep_id, enc in self._data.keys.items():
            dec = _decrypt(enc, password, salt)
            if dec is not None:
                result[ep_id] = dec
        return result

    def get_key(self, endpoint_id: str, password: str) -> str | None:
        """指定エンドポイントのAPIキーを返す。"""
        keys = self.load_keys(password)
        return keys.get(endpoint_id)

    def teardown(self) -> None:
        """ボルトを削除（全キーを消去）する。"""
        self._data = VaultData()
