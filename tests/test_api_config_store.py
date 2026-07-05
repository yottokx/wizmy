from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.core.llm.schemas import Endpoint
from src.storage import api_config_store
from src.storage.api_config_store import ApiConfigStore


def test_corrupted_config_is_quarantined_and_defaults_loaded(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{broken", encoding="utf-8")

    store = ApiConfigStore(config_path)

    broken_files = list(tmp_path.glob("config.json.broken-*"))
    assert len(broken_files) == 1
    assert broken_files[0].read_text(encoding="utf-8") == "{broken"
    assert not config_path.exists()
    assert store.get_endpoints() == []

    store.save()

    assert config_path.exists()
    assert json.loads(config_path.read_text(encoding="utf-8"))["endpoints"] == []


def test_save_keeps_existing_file_when_atomic_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"llm_profiles": [], "endpoints": []}), encoding="utf-8")
    original = config_path.read_text(encoding="utf-8")
    store = ApiConfigStore(config_path)
    store.upsert_endpoint(
        Endpoint(
            id="ep-1",
            name="テスト",
            base_url="http://127.0.0.1:11434",
        )
    )

    def fail_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(api_config_store.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        store.save()

    assert config_path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".config.json.*.tmp")) == []
