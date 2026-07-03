"""
アプリケーションコンテキスト。

サービスとストレージの初期化と依存関係の管理を行う。
NiceGUI の app.on_startup/on_shutdown で使用する。
"""

from __future__ import annotations

from .config import AppSettings
from .services.api_config import ApiConfigService
from .services.ai_jobs import AIJobService
from .services.chat import ChatService
from .services.character import CharacterService
from .services.character_generation import CharacterGenerationService
from .services.danbooru_prompt import DanbooruPromptService
from .services.group_chat import GroupChatService
from .services.group_chat_turns import GroupChatTurnService
from .services.image_generation import ImageGenerationService
from .services.tts import TTSService
from .storage.api_config_store import ApiConfigStore
from .storage.chat_repository import ChatRepository
from .storage.character_repository import CharacterRepository
from .storage.group_chat_repository import GroupChatRepository


class AppContext:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._api_config_store = ApiConfigStore(settings.config_file)
        self._character_repo = CharacterRepository(settings.db_file)
        self._chat_repo = ChatRepository(settings.db_file)
        self._group_chat_repo = GroupChatRepository(settings.db_file)

        self.api_config = ApiConfigService(self._api_config_store, settings.data_dir)
        self.ai_jobs = AIJobService()
        self.chats = ChatService(self._chat_repo)
        self.group_chats = GroupChatService(self._group_chat_repo, settings.data_dir)
        self.group_chat_turns = GroupChatTurnService()
        self.characters = CharacterService(self._character_repo, settings.data_dir)
        self.generation = CharacterGenerationService(self.characters)
        self.danbooru_prompt = DanbooruPromptService(self.api_config, self.ai_jobs)
        self.image_generation = ImageGenerationService(self.api_config, self.ai_jobs)
        self.tts = TTSService(self.api_config, self.ai_jobs)

    async def startup(self) -> None:
        await self._character_repo.initialize()
        await self._chat_repo.initialize()
        await self._group_chat_repo.initialize()

    async def shutdown(self) -> None:
        pass


_context: AppContext | None = None


def init_context(settings: AppSettings) -> AppContext:
    global _context
    _context = AppContext(settings)
    return _context


def get_context() -> AppContext:
    if _context is None:
        raise RuntimeError("AppContext が初期化されていません。init_context() を先に呼び出してください。")
    return _context
