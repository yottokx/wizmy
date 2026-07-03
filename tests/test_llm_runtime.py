from __future__ import annotations

from typing import Any

import pytest

from src.core.llm.schemas import Endpoint, LLMProfile
from src.services import llm_runtime as runtime_module
from src.services.llm_runtime import (
    API_KEY_LOCKED,
    ENDPOINT_NOT_FOUND,
    MODEL_ID_MISSING,
    PROFILE_NOT_FOUND,
    LLMRuntimeError,
    build_configured_llm,
)


class _StubApiConfig:
    def __init__(
        self,
        *,
        profile: LLMProfile | None = None,
        endpoint: Endpoint | None = None,
        api_key: str | None = None,
        locked: bool = False,
    ) -> None:
        self.profile = profile
        self.endpoint = endpoint
        self.api_key = api_key
        self.locked = locked
        self.get_api_key_calls: list[tuple[str, str | None]] = []

    def get_llm_profile(self, profile_id: str) -> LLMProfile | None:
        if self.profile and self.profile.id == profile_id:
            return self.profile
        return None

    def get_endpoint(self, endpoint_id: str) -> Endpoint | None:
        if self.endpoint and self.endpoint.id == endpoint_id:
            return self.endpoint
        return None

    def get_api_key(self, endpoint_id: str, password: str | None) -> str | None:
        self.get_api_key_calls.append((endpoint_id, password))
        return self.api_key

    def is_api_key_locked(self, endpoint_id: str, api_key: str | None) -> bool:
        return self.locked


def test_build_configured_llm_raises_when_profile_missing() -> None:
    with pytest.raises(LLMRuntimeError) as exc:
        build_configured_llm(_StubApiConfig(), "missing-profile", None)  # type: ignore[arg-type]

    assert exc.value.kind == PROFILE_NOT_FOUND
    assert str(exc.value) == "LLMプロファイルを選択してください"


def test_build_configured_llm_raises_when_model_id_missing() -> None:
    profile = LLMProfile(id="profile-1", name="テストプロファイル", endpoint_id="endpoint-1", model_id="")

    with pytest.raises(LLMRuntimeError) as exc:
        build_configured_llm(_StubApiConfig(profile=profile), profile.id, None)  # type: ignore[arg-type]

    assert exc.value.kind == MODEL_ID_MISSING
    assert str(exc.value) == "モデルIDが未設定です。設定画面でLLMプロファイルのモデルを設定してください。"


def test_build_configured_llm_raises_when_endpoint_missing() -> None:
    profile = LLMProfile(id="profile-1", name="テストプロファイル", endpoint_id="endpoint-1", model_id="test-model")

    with pytest.raises(LLMRuntimeError) as exc:
        build_configured_llm(_StubApiConfig(profile=profile), profile.id, None)  # type: ignore[arg-type]

    assert exc.value.kind == ENDPOINT_NOT_FOUND
    assert str(exc.value) == "エンドポイントが見つかりません"


def test_build_configured_llm_raises_when_api_key_locked() -> None:
    profile = LLMProfile(id="profile-1", name="テストプロファイル", endpoint_id="endpoint-1", model_id="test-model")
    endpoint = Endpoint(id="endpoint-1", name="テストエンドポイント")
    api_config = _StubApiConfig(profile=profile, endpoint=endpoint, api_key=None, locked=True)

    with pytest.raises(LLMRuntimeError) as exc:
        build_configured_llm(api_config, profile.id, "vault-password")  # type: ignore[arg-type]

    assert exc.value.kind == API_KEY_LOCKED
    assert str(exc.value) == "このエンドポイントにはAPIキーが設定されています。APIキーボルトをロック解除してください。"
    assert api_config.get_api_key_calls == [("endpoint-1", "vault-password")]


def test_build_configured_llm_returns_created_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = LLMProfile(id="profile-1", name="テストプロファイル", endpoint_id="endpoint-1", model_id="test-model")
    endpoint = Endpoint(id="endpoint-1", name="テストエンドポイント")
    api_config = _StubApiConfig(profile=profile, endpoint=endpoint, api_key="test-api-key")
    created_llm = object()
    calls: list[tuple[LLMProfile, Endpoint, str | None]] = []

    def fake_create_llm(profile_arg: LLMProfile, endpoint_arg: Endpoint, api_key_arg: str | None) -> Any:
        calls.append((profile_arg, endpoint_arg, api_key_arg))
        return created_llm

    monkeypatch.setattr(runtime_module, "create_llm", fake_create_llm)

    llm = build_configured_llm(api_config, profile.id, "vault-password")  # type: ignore[arg-type]

    assert llm is created_llm
    assert api_config.get_api_key_calls == [("endpoint-1", "vault-password")]
    assert calls == [(profile, endpoint, "test-api-key")]
