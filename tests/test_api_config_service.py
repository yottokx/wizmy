from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.core.gen_server.schemas import GEN_SERVER_MODE_SDXL_IMAGE
from src.core.llm.schemas import Endpoint
from src.services import api_config as api_config_module
from src.services.api_config import ApiConfigService
from src.storage.api_config_store import ApiConfigStore
from src.ui.pages.settings.endpoints import endpoint_with_updates


def test_endpoint_with_updates_validates_base_url() -> None:
    endpoint = Endpoint(id="endpoint-1", name="旧", base_url="http://localhost:11434")

    updated = endpoint_with_updates(
        endpoint,
        name="新",
        ep_type="openai_compat",
        base_url="http://localhost:1234/",
    )

    assert updated.name == "新"
    assert updated.type == "openai_compat"
    assert updated.base_url == "http://localhost:1234"


async def test_fetch_gen_server_models_ignores_non_dict_items_before_mode_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ApiConfigStore(tmp_path / "config.json")
    service = ApiConfigService(store)
    endpoint = service.create_gen_server_endpoint("テスト", "http://127.0.0.1:8008/v1")

    class StubResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return {
                "models": [
                    "broken",
                    None,
                    {"id": "image-1", "mode": GEN_SERVER_MODE_SDXL_IMAGE, "display_name": "Image"},
                    {"id": "", "mode": GEN_SERVER_MODE_SDXL_IMAGE},
                    {"id": "voice-1", "mode": "voice_clone"},
                ]
            }

    class StubAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "StubAsyncClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def get(self, url: str) -> StubResponse:
            return StubResponse()

    monkeypatch.setattr(api_config_module.httpx, "AsyncClient", StubAsyncClient)

    models = await service.fetch_gen_server_models(endpoint.id, mode=GEN_SERVER_MODE_SDXL_IMAGE)

    assert models == [{"id": "image-1", "mode": GEN_SERVER_MODE_SDXL_IMAGE, "display_name": "Image"}]
