"""list_recent 系(全キャラ/全グループ横断の最近セッション)のテスト。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from src.core.chat.sessions import ChatSessionRecord
from src.core.group_chat.sessions import GroupChatSessionRecord
from src.services.chat import ChatService
from src.services.group_chat import GroupChatService
from src.storage.chat_repository import ChatRepository
from src.storage.group_chat_repository import GroupChatRepository


class ChatListRecentTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = ChatRepository(Path(self._tmp.name) / "chat.db")
        self.service = ChatService(self.repo)
        await self.service.initialize()

    async def test_list_recent_spans_characters_in_updated_order(self) -> None:
        for index, character_id in enumerate(["char-a", "char-b", "char-c"]):
            await self.repo.save(
                ChatSessionRecord(
                    id=f"session-{index}",
                    character_id=character_id,
                    title=f"タイトル{index}",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
            )

        recent = await self.service.list_recent(10)
        self.assertEqual(
            ["session-2", "session-1", "session-0"],
            [session.id for session in recent],
        )
        self.assertEqual(
            {"char-a", "char-b", "char-c"},
            {session.character_id for session in recent},
        )

    async def test_list_recent_respects_limit_and_updates(self) -> None:
        for index in range(3):
            await self.repo.save(
                ChatSessionRecord(id=f"session-{index}", character_id="char-a")
            )
        # 最古のセッションを更新すると先頭に来る
        oldest = await self.repo.get("session-0")
        assert oldest is not None
        await self.repo.save(oldest)

        recent = await self.service.list_recent(2)
        self.assertEqual(["session-0", "session-2"], [session.id for session in recent])

    async def test_list_recent_empty(self) -> None:
        self.assertEqual([], await self.service.list_recent())


class GroupListRecentSessionsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        data_dir = Path(self._tmp.name)
        self.repo = GroupChatRepository(data_dir / "group.db")
        self.service = GroupChatService(self.repo, data_dir)
        await self.service.initialize()

    async def test_list_recent_sessions_spans_groups_in_updated_order(self) -> None:
        for index, group_id in enumerate(["group-a", "group-b"]):
            await self.repo.save_session(
                GroupChatSessionRecord(
                    id=f"session-{index}",
                    group_id=group_id,
                    title=f"タイトル{index}",
                )
            )

        recent = await self.service.list_recent_sessions(10)
        self.assertEqual(["session-1", "session-0"], [session.id for session in recent])

        limited = await self.service.list_recent_sessions(1)
        self.assertEqual(["session-1"], [session.id for session in limited])

    async def test_list_recent_sessions_empty(self) -> None:
        self.assertEqual([], await self.service.list_recent_sessions())


if __name__ == "__main__":
    unittest.main()
