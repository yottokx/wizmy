"""
API設定の永続化ストア（JSON ファイルベース）。

エンドポイント・LLMプロファイル・キャラ生成プリセット・ボルトデータを
単一の JSON ファイルで管理する。
人間が読めることとエクスポート/バックアップの容易さを重視してJSONを採用。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.chat.schemas import ChatMode, UserPersona, default_chat_modes
from ..core.gen_server.schemas import (
    GEN_SERVER_MODE_SDXL_IMAGE,
    GEN_SERVER_MODES,
    GenServerConfig,
    GenServerEndpoint,
    clean_gen_server_mode_defaults,
    default_gen_server_mode_defaults,
)
from ..core.image_generation.schemas import (
    IMAGE_PROVIDER_WIZMY_GEN_SERVER,
    ImageGenerationConfig,
    ImageGenerationProfile,
    clean_image_generation_params,
)
from ..core.llm.schemas import AppLLMConfig, Endpoint, GenerationPreset, LLMProfile
from ..core.tts.schemas import TTSConfig, TTSEndpoint
from .key_vault import KeyVault, VaultData

_DEFAULT_ENDPOINT_ID = "ep-ollama-local"
_DEFAULT_PROFILE_ID = "profile-ollama-local"
_GEN_SERVER_ASSIGNABLE_MODES = tuple(mode for mode in GEN_SERVER_MODES if mode != GEN_SERVER_MODE_SDXL_IMAGE)
_logger = logging.getLogger(__name__)


def _new_id() -> str:
    return str(uuid.uuid4())[:8]


def _default_data() -> dict:
    return {
        "endpoints": [],
        "llm_profiles": [],
        "generation_presets": [],
        "chat_modes": [mode.model_dump() for mode in default_chat_modes()],
        "user_personas": [],
        "app_llm_config": {
            "generation_profile_id": "",
            "chat_profile_id": "",
        },
        "tts_config": {
            "endpoints": [],
            "default_endpoint_id": "",
            "narrator": {},
            "narrator_voice": None,
        },
        "gen_server_config": {
            "endpoints": [],
            "mode_assignments": {},
            "mode_defaults": {},
            "voice_chunking_enabled": True,
            "voice_chunk_min_chars": 80,
        },
        "image_generation_config": {
            "profiles": [],
            "default_profile_id": "",
        },
        "vault_salt": "",
        "vault_verifier": "",
        "vault_keys": {},
    }


def _ordered_records(records: list[dict], ordered_ids: list[str]) -> list[dict]:
    by_id = {record.get("id"): record for record in records}
    seen = set()
    ordered: list[dict] = []
    for record_id in ordered_ids:
        if record_id in by_id and record_id not in seen:
            ordered.append(by_id[record_id])
            seen.add(record_id)
    ordered.extend(record for record in records if record.get("id") not in seen)
    return ordered


def _with_defaults(data: dict) -> dict:
    defaults = _default_data()
    merged = {**defaults, **data}
    app_llm_config = data.get("app_llm_config") or {}
    merged["app_llm_config"] = {
        **defaults["app_llm_config"],
        **app_llm_config,
    }
    if "chat_profile_id" not in app_llm_config:
        merged["app_llm_config"]["chat_profile_id"] = merged["app_llm_config"].get("generation_profile_id", "")
    merged["tts_config"] = {
        **defaults["tts_config"],
        **(data.get("tts_config") or {}),
    }
    merged["gen_server_config"] = {
        **defaults["gen_server_config"],
        **(data.get("gen_server_config") or {}),
    }
    merged["image_generation_config"] = {
        **defaults["image_generation_config"],
        **(data.get("image_generation_config") or {}),
    }
    return merged


class ApiConfigStore:
    """API設定の読み書きを担うストア。"""

    def __init__(self, config_path: Path) -> None:
        self._path = config_path
        self._data: dict[str, Any] = {}
        self._vault: KeyVault | None = None
        self.load()

    def load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("設定ファイルのJSONルートがオブジェクトではありません。")
                self._data = self._migrate(raw)
            except Exception:
                broken_path = self._quarantine_broken_config()
                _logger.exception(
                    "設定ファイルの読み込みに失敗したため退避しました: %s -> %s",
                    self._path,
                    broken_path,
                )
                self._data = _default_data()
        else:
            self._data = _default_data()

        self._cleanup_defaults()
        vault_data = VaultData.from_dict(self._data)
        self._vault = KeyVault(vault_data)

    def _cleanup_defaults(self) -> None:
        """初期デフォルト値として自動生成されたモデル未設定プロファイルを除去する。"""
        profiles = self._data.get("llm_profiles", [])
        cleaned = [p for p in profiles if not (p.get("id") == _DEFAULT_PROFILE_ID and p.get("model_id", "") == "")]
        if len(cleaned) != len(profiles):
            self._data["llm_profiles"] = cleaned
            cfg = self._data.get("app_llm_config", {})
            if cfg.get("generation_profile_id") == _DEFAULT_PROFILE_ID:
                cfg["generation_profile_id"] = cleaned[0]["id"] if cleaned else ""
            if cfg.get("chat_profile_id") == _DEFAULT_PROFILE_ID:
                cfg["chat_profile_id"] = cfg.get("generation_profile_id") or (cleaned[0]["id"] if cleaned else "")

        cfg = self._data.setdefault("app_llm_config", {})
        valid_ids = [p.get("id") for p in self._data.get("llm_profiles", []) if p.get("id")]
        fallback_id = valid_ids[0] if valid_ids else ""
        if cfg.get("generation_profile_id") and cfg.get("generation_profile_id") not in valid_ids:
            cfg["generation_profile_id"] = fallback_id
        if cfg.get("chat_profile_id") and cfg.get("chat_profile_id") not in valid_ids:
            cfg["chat_profile_id"] = cfg.get("generation_profile_id") or fallback_id

        gen_cfg = self._data.setdefault("gen_server_config", {})
        raw_endpoints = gen_cfg.get("endpoints", [])
        if not isinstance(raw_endpoints, list):
            raw_endpoints = []
        endpoints = [ep for ep in raw_endpoints if isinstance(ep, dict) and ep.get("id")]
        valid_gen_ids = {ep.get("id") for ep in endpoints}
        assignments = gen_cfg.get("mode_assignments", {})
        if not isinstance(assignments, dict):
            assignments = {}
        mode_defaults = gen_cfg.get("mode_defaults", {})
        if not isinstance(mode_defaults, dict):
            mode_defaults = {}
        gen_cfg["endpoints"] = endpoints
        gen_cfg["mode_assignments"] = {
            mode: endpoint_id
            for mode, endpoint_id in assignments.items()
            if mode in GEN_SERVER_MODES and endpoint_id in valid_gen_ids
        }
        gen_cfg["mode_defaults"] = {
            mode: defaults
            for mode, defaults in mode_defaults.items()
            if mode in GEN_SERVER_MODES and isinstance(defaults, dict)
        }
        image_cfg = self._data.setdefault("image_generation_config", {})
        if not isinstance(image_cfg.get("profiles"), list):
            image_cfg["profiles"] = []
        if not isinstance(image_cfg.get("default_profile_id"), str):
            image_cfg["default_profile_id"] = ""
        self._migrate_sdxl_defaults_to_image_profile(gen_cfg, image_cfg)
        valid_profile_ids = [
            profile.get("id")
            for profile in image_cfg.get("profiles", [])
            if isinstance(profile, dict) and profile.get("id")
        ]
        if image_cfg.get("default_profile_id") not in valid_profile_ids:
            image_cfg["default_profile_id"] = valid_profile_ids[0] if valid_profile_ids else ""

    def _migrate_sdxl_defaults_to_image_profile(self, gen_cfg: dict, image_cfg: dict) -> None:
        """旧SDXLデフォルト設定を画像生成プロファイルへ移す。"""
        profiles = image_cfg.get("profiles", [])
        if profiles:
            gen_cfg.get("mode_defaults", {}).pop(GEN_SERVER_MODE_SDXL_IMAGE, None)
            gen_cfg.get("mode_assignments", {}).pop(GEN_SERVER_MODE_SDXL_IMAGE, None)
            return

        mode_defaults = gen_cfg.get("mode_defaults", {})
        sdxl_defaults = {}
        if isinstance(mode_defaults, dict):
            sdxl_defaults = clean_gen_server_mode_defaults(
                GEN_SERVER_MODE_SDXL_IMAGE,
                mode_defaults.get(GEN_SERVER_MODE_SDXL_IMAGE, {}),
            )
        endpoint_id = ""
        assignments = gen_cfg.get("mode_assignments", {})
        if isinstance(assignments, dict):
            endpoint_id = str(assignments.get(GEN_SERVER_MODE_SDXL_IMAGE) or "")
        if not sdxl_defaults and not endpoint_id:
            return

        values = default_gen_server_mode_defaults(GEN_SERVER_MODE_SDXL_IMAGE)
        values.update(sdxl_defaults)
        image_cfg["profiles"] = [
            ImageGenerationProfile(
                id=_new_id(),
                name="SDXL画像生成",
                provider=IMAGE_PROVIDER_WIZMY_GEN_SERVER,
                endpoint_id=endpoint_id,
                model_id=str(values.get("model_id") or ""),
                prompt=str(values.get("prompt") or ""),
                negative_prompt=str(values.get("negative_prompt") or ""),
                params=clean_image_generation_params(values),
            ).model_dump()
        ]
        image_cfg["default_profile_id"] = image_cfg["profiles"][0]["id"]
        gen_cfg.get("mode_defaults", {}).pop(GEN_SERVER_MODE_SDXL_IMAGE, None)
        gen_cfg.get("mode_assignments", {}).pop(GEN_SERVER_MODE_SDXL_IMAGE, None)

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._vault:
            self._data.update(self._vault.data.to_dict())
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp_path = Path(tmp.name)
                json.dump(self._data, tmp, ensure_ascii=False, indent=2)
                tmp.write("\n")
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_path, self._path)
        except Exception:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink()
            raise

    def _quarantine_broken_config(self) -> Path:
        broken_path = self._next_broken_config_path()
        os.replace(self._path, broken_path)
        return broken_path

    def _next_broken_config_path(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        base = self._path.with_name(f"{self._path.name}.broken-{timestamp}")
        if not base.exists():
            return base
        for suffix in range(1, 1000):
            candidate = self._path.with_name(f"{base.name}-{suffix}")
            if not candidate.exists():
                return candidate
        raise RuntimeError("破損した設定ファイルの退避先を作成できません。")

    def _migrate(self, data: dict) -> dict:
        """旧Streamlit版フォーマットから新フォーマットへ変換する。"""
        if "llm_profiles" in data:
            return _with_defaults(data)

        url_to_ep: dict[str, dict] = {}
        new_profiles: list[dict] = []

        for p in data.get("presets", []):
            provider = p.get("provider", "ollama")
            url = p.get("endpoint", "http://localhost:11434").rstrip("/")
            ep_type = "ollama" if provider == "ollama" else "openai_compat"

            if url not in url_to_ep:
                url_to_ep[url] = {
                    "id": _new_id(),
                    "name": p.get("name", url),
                    "type": ep_type,
                    "base_url": url,
                }

            new_profiles.append(
                {
                    "id": p.get("id", _new_id()),
                    "name": p.get("name", ""),
                    "endpoint_id": url_to_ep[url]["id"],
                    "model_id": p.get("model", ""),
                    "temperature": p.get("temperature", 0.8),
                    "reasoning_enabled": p.get("reasoning", False),
                    "max_tokens": None,
                    "extra_params": {},
                }
            )

        migrated: dict[str, Any] = {
            "endpoints": list(url_to_ep.values()) or _default_data()["endpoints"],
            "llm_profiles": new_profiles or _default_data()["llm_profiles"],
            "generation_presets": data.get("generation_presets", []),
            "app_llm_config": {
                "generation_profile_id": (data.get("selected_preset_id", "") or _DEFAULT_PROFILE_ID),
            },
        }
        for key in ("vault_salt", "vault_verifier", "vault_keys"):
            migrated[key] = data.get(key, "" if key != "vault_keys" else {})
        return _with_defaults(migrated)

    # ─── エンドポイント ───

    def get_endpoints(self) -> list[Endpoint]:
        return [Endpoint(**ep) for ep in self._data.get("endpoints", [])]

    def get_endpoint(self, endpoint_id: str) -> Endpoint | None:
        for ep in self._data.get("endpoints", []):
            if ep["id"] == endpoint_id:
                return Endpoint(**ep)
        return None

    def upsert_endpoint(self, endpoint: Endpoint) -> None:
        endpoints = self._data.setdefault("endpoints", [])
        for i, ep in enumerate(endpoints):
            if ep["id"] == endpoint.id:
                endpoints[i] = endpoint.model_dump()
                return
        endpoints.append(endpoint.model_dump())

    def delete_endpoint(self, endpoint_id: str) -> None:
        self._data["endpoints"] = [ep for ep in self._data.get("endpoints", []) if ep["id"] != endpoint_id]
        if self._vault:
            self._vault.delete_key(endpoint_id)

    def reorder_endpoints(self, ordered_ids: list[str]) -> None:
        endpoints = self._data.setdefault("endpoints", [])
        self._data["endpoints"] = _ordered_records(endpoints, ordered_ids)

    # ─── LLMプロファイル ───

    def get_llm_profiles(self) -> list[LLMProfile]:
        return [LLMProfile(**p) for p in self._data.get("llm_profiles", [])]

    def get_llm_profile(self, profile_id: str) -> LLMProfile | None:
        for p in self._data.get("llm_profiles", []):
            if p["id"] == profile_id:
                return LLMProfile(**p)
        return None

    def upsert_llm_profile(self, profile: LLMProfile) -> None:
        profiles = self._data.setdefault("llm_profiles", [])
        for i, p in enumerate(profiles):
            if p["id"] == profile.id:
                profiles[i] = profile.model_dump()
                return
        profiles.append(profile.model_dump())

    def delete_llm_profile(self, profile_id: str) -> None:
        self._data["llm_profiles"] = [p for p in self._data.get("llm_profiles", []) if p["id"] != profile_id]
        cfg = self._data.setdefault("app_llm_config", {})
        remaining_ids = [p.get("id") for p in self._data.get("llm_profiles", []) if p.get("id")]
        fallback_id = remaining_ids[0] if remaining_ids else ""
        if cfg.get("generation_profile_id") == profile_id:
            cfg["generation_profile_id"] = fallback_id
        if cfg.get("chat_profile_id") == profile_id:
            cfg["chat_profile_id"] = cfg.get("generation_profile_id") or fallback_id

    def reorder_llm_profiles(self, ordered_ids: list[str]) -> None:
        profiles = self._data.setdefault("llm_profiles", [])
        self._data["llm_profiles"] = _ordered_records(profiles, ordered_ids)

    # ─── キャラ生成プリセット ───

    def get_generation_presets(self) -> list[GenerationPreset]:
        return [GenerationPreset(**p) for p in self._data.get("generation_presets", [])]

    def get_generation_preset(self, preset_id: str) -> GenerationPreset | None:
        for p in self._data.get("generation_presets", []):
            if p["id"] == preset_id:
                return GenerationPreset(**p)
        return None

    def upsert_generation_preset(self, preset: GenerationPreset) -> None:
        presets = self._data.setdefault("generation_presets", [])
        for i, p in enumerate(presets):
            if p["id"] == preset.id:
                presets[i] = preset.model_dump()
                return
        presets.append(preset.model_dump())

    def delete_generation_preset(self, preset_id: str) -> None:
        self._data["generation_presets"] = [p for p in self._data.get("generation_presets", []) if p["id"] != preset_id]

    def reorder_generation_presets(self, ordered_ids: list[str]) -> None:
        presets = self._data.setdefault("generation_presets", [])
        self._data["generation_presets"] = _ordered_records(presets, ordered_ids)

    # ─── チャットモード ───

    def get_chat_modes(self) -> list[ChatMode]:
        return [ChatMode(**mode) for mode in self._data.get("chat_modes", [])]

    def get_chat_mode(self, mode_id: str) -> ChatMode | None:
        for mode in self._data.get("chat_modes", []):
            if mode["id"] == mode_id:
                return ChatMode(**mode)
        return None

    def upsert_chat_mode(self, mode: ChatMode) -> None:
        modes = self._data.setdefault("chat_modes", [])
        for index, current in enumerate(modes):
            if current["id"] == mode.id:
                modes[index] = mode.model_dump()
                return
        modes.append(mode.model_dump())

    def delete_chat_mode(self, mode_id: str) -> None:
        self._data["chat_modes"] = [mode for mode in self._data.get("chat_modes", []) if mode["id"] != mode_id]

    def reorder_chat_modes(self, ordered_ids: list[str]) -> None:
        modes = self._data.setdefault("chat_modes", [])
        self._data["chat_modes"] = _ordered_records(modes, ordered_ids)

    # ─── ユーザーペルソナ ───

    def get_user_personas(self) -> list[UserPersona]:
        return [UserPersona(**persona) for persona in self._data.get("user_personas", [])]

    def get_user_persona(self, persona_id: str) -> UserPersona | None:
        for persona in self._data.get("user_personas", []):
            if persona["id"] == persona_id:
                return UserPersona(**persona)
        return None

    def upsert_user_persona(self, persona: UserPersona) -> None:
        personas = self._data.setdefault("user_personas", [])
        payload = persona.model_dump(mode="json")
        for index, current in enumerate(personas):
            if current["id"] == persona.id:
                personas[index] = payload
                return
        personas.append(payload)

    def delete_user_persona(self, persona_id: str) -> None:
        self._data["user_personas"] = [
            persona for persona in self._data.get("user_personas", []) if persona["id"] != persona_id
        ]

    def reorder_user_personas(self, ordered_ids: list[str]) -> None:
        personas = self._data.setdefault("user_personas", [])
        self._data["user_personas"] = _ordered_records(personas, ordered_ids)

    # ─── 生成選択肢 ───

    def get_option_lists(self) -> dict[str, list[str]]:
        """世界観・年齢帯・性別の選択肢リストを取得する。未設定ならデフォルトを返す。"""
        from ..core.character_generation.prompts import AGE_OPTIONS, GENDER_OPTIONS, WORLD_OPTIONS

        stored = self._data.get("generation_option_lists", {})
        return {
            "world": list(stored.get("world", WORLD_OPTIONS)),
            "age": list(stored.get("age", AGE_OPTIONS)),
            "gender": list(stored.get("gender", GENDER_OPTIONS)),
        }

    def save_option_lists(self, lists: dict[str, list[str]]) -> None:
        """世界観・年齢帯・性別の選択肢リストを保存する。"""
        self._data["generation_option_lists"] = {k: list(v) for k, v in lists.items()}
        self.save()

    # ─── アプリLLM設定 ───

    def get_app_llm_config(self) -> AppLLMConfig:
        return AppLLMConfig(**self._data.get("app_llm_config", {}))

    def save_app_llm_config(self, config: AppLLMConfig) -> None:
        self._data["app_llm_config"] = config.model_dump()

    # ─── 画像生成プロファイル ───

    def get_image_generation_config(self) -> ImageGenerationConfig:
        return ImageGenerationConfig(**self._data.get("image_generation_config", {}))

    def save_image_generation_config(self, config: ImageGenerationConfig) -> None:
        self._data["image_generation_config"] = config.model_dump()

    def get_image_generation_profiles(self) -> list[ImageGenerationProfile]:
        return self.get_image_generation_config().profiles

    def get_image_generation_profile(self, profile_id: str) -> ImageGenerationProfile | None:
        for profile in self.get_image_generation_config().profiles:
            if profile.id == profile_id:
                return profile
        return None

    def upsert_image_generation_profile(self, profile: ImageGenerationProfile) -> None:
        config = self.get_image_generation_config()
        profiles = list(config.profiles)
        for index, current in enumerate(profiles):
            if current.id == profile.id:
                profiles[index] = profile
                break
        else:
            profiles.append(profile)
        if not config.default_profile_id:
            config.default_profile_id = profile.id
        config.profiles = profiles
        self.save_image_generation_config(config)

    def delete_image_generation_profile(self, profile_id: str) -> None:
        config = self.get_image_generation_config()
        config.profiles = [profile for profile in config.profiles if profile.id != profile_id]
        if config.default_profile_id == profile_id:
            config.default_profile_id = config.profiles[0].id if config.profiles else ""
        self.save_image_generation_config(config)

    def reorder_image_generation_profiles(self, ordered_ids: list[str]) -> None:
        config = self.get_image_generation_config()
        records = [profile.model_dump() for profile in config.profiles]
        config.profiles = [ImageGenerationProfile(**record) for record in _ordered_records(records, ordered_ids)]
        self.save_image_generation_config(config)

    # ─── TTS設定 ───

    def get_tts_config(self) -> TTSConfig:
        return TTSConfig(**self._data.get("tts_config", {}))

    def save_tts_config(self, config: TTSConfig) -> None:
        self._data["tts_config"] = config.model_dump(mode="json")

    def get_tts_endpoint(self, endpoint_id: str) -> TTSEndpoint | None:
        for endpoint in self.get_tts_config().endpoints:
            if endpoint.id == endpoint_id:
                return endpoint
        return None

    def upsert_tts_endpoint(self, endpoint: TTSEndpoint) -> None:
        config = self.get_tts_config()
        endpoints = list(config.endpoints)
        for index, current in enumerate(endpoints):
            if current.id == endpoint.id:
                endpoints[index] = endpoint
                break
        else:
            endpoints.append(endpoint)
        if not config.default_endpoint_id:
            config.default_endpoint_id = endpoint.id
        config.endpoints = endpoints
        self.save_tts_config(config)

    def delete_tts_endpoint(self, endpoint_id: str) -> None:
        config = self.get_tts_config()
        config.endpoints = [ep for ep in config.endpoints if ep.id != endpoint_id]
        if config.default_endpoint_id == endpoint_id:
            config.default_endpoint_id = config.endpoints[0].id if config.endpoints else ""
        self.save_tts_config(config)

    def reorder_tts_endpoints(self, ordered_ids: list[str]) -> None:
        config = self.get_tts_config()
        records = [endpoint.model_dump() for endpoint in config.endpoints]
        config.endpoints = [TTSEndpoint(**record) for record in _ordered_records(records, ordered_ids)]
        self.save_tts_config(config)

    # ─── Wizmy-Gen-Server設定 ───

    def get_gen_server_config(self) -> GenServerConfig:
        return GenServerConfig(**self._data.get("gen_server_config", {}))

    def save_gen_server_config(self, config: GenServerConfig) -> None:
        self._data["gen_server_config"] = config.model_dump()

    def get_gen_server_endpoint(self, endpoint_id: str) -> GenServerEndpoint | None:
        for endpoint in self.get_gen_server_config().endpoints:
            if endpoint.id == endpoint_id:
                return endpoint
        return None

    def upsert_gen_server_endpoint(self, endpoint: GenServerEndpoint) -> None:
        config = self.get_gen_server_config()
        endpoints = list(config.endpoints)
        is_first_endpoint = not endpoints
        for index, current in enumerate(endpoints):
            if current.id == endpoint.id:
                endpoints[index] = endpoint
                break
        else:
            endpoints.append(endpoint)
        config.endpoints = endpoints
        if is_first_endpoint:
            config.mode_assignments = {mode: endpoint.id for mode in _GEN_SERVER_ASSIGNABLE_MODES}
        self.save_gen_server_config(config)

    def delete_gen_server_endpoint(self, endpoint_id: str) -> None:
        config = self.get_gen_server_config()
        config.endpoints = [ep for ep in config.endpoints if ep.id != endpoint_id]
        config.mode_assignments = {
            mode: current_id for mode, current_id in config.mode_assignments.items() if current_id != endpoint_id
        }
        self.save_gen_server_config(config)
        image_config = self.get_image_generation_config()
        image_config.profiles = [
            profile.model_copy(update={"endpoint_id": ""})
            if profile.provider == IMAGE_PROVIDER_WIZMY_GEN_SERVER and profile.endpoint_id == endpoint_id
            else profile
            for profile in image_config.profiles
        ]
        self.save_image_generation_config(image_config)

    def reorder_gen_server_endpoints(self, ordered_ids: list[str]) -> None:
        config = self.get_gen_server_config()
        records = [endpoint.model_dump() for endpoint in config.endpoints]
        config.endpoints = [GenServerEndpoint(**record) for record in _ordered_records(records, ordered_ids)]
        self.save_gen_server_config(config)

    def set_gen_server_mode_assignment(self, mode: str, endpoint_id: str) -> None:
        config = self.get_gen_server_config()
        if mode not in _GEN_SERVER_ASSIGNABLE_MODES:
            return
        valid_ids = {endpoint.id for endpoint in config.endpoints}
        if endpoint_id and endpoint_id not in valid_ids:
            return
        if endpoint_id:
            config.mode_assignments[mode] = endpoint_id
        else:
            config.mode_assignments.pop(mode, None)
        self.save_gen_server_config(config)

    def set_gen_server_mode_defaults(self, mode: str, defaults: dict[str, Any]) -> None:
        config = self.get_gen_server_config()
        if mode not in _GEN_SERVER_ASSIGNABLE_MODES:
            return
        config.mode_defaults[mode] = defaults
        self.save_gen_server_config(config)

    def set_gen_server_voice_chunking(self, *, enabled: bool, min_chars: int) -> None:
        config = self.get_gen_server_config()
        config.voice_chunking_enabled = bool(enabled)
        config.voice_chunk_min_chars = max(1, int(min_chars))
        self.save_gen_server_config(config)

    # ─── キーボルト ───

    @property
    def vault(self) -> KeyVault:
        if self._vault is None:
            raise RuntimeError("ボルトが初期化されていません。")
        return self._vault

    def new_id(self) -> str:
        return _new_id()
