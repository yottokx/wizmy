"""グループメンバー/ペルソナのメディア参照をグループ所有パスへ移行する。

背景: 適応コピー作成時にメディア実体をコピーしない旧実装では、メンバーの
画像・音声が元キャラクターの characters/{id}/ 配下を参照したままになり、
元キャラクター削除(メディアディレクトリごと削除)で道連れに壊れていた。
本ツールは既存グループのメディア実体を groups/{gid}/ 配下へ複製し、
参照を書き換える(新規作成分はサービス側で自動コピーされるため不要)。

Usage (wizmy/ ディレクトリから実行):
    .venv/Scripts/python tools/migrate_group_member_media.py            # dry-run
    .venv/Scripts/python tools/migrate_group_member_media.py --apply    # 実行
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import get_settings  # noqa: E402
from src.services.group_chat import GroupChatService  # noqa: E402
from src.storage.group_chat_repository import GroupChatRepository  # noqa: E402


async def run(apply: bool) -> None:
    settings = get_settings()
    service = GroupChatService(GroupChatRepository(settings.db_file), settings.data_dir)
    await service.initialize()

    groups = await service.list_all()
    if not groups:
        print("グループはありません。")
        return

    mode = "apply" if apply else "dry-run"
    total = 0
    for group in groups:
        changes = await service.localize_group_media(group.id, dry_run=not apply)
        if not changes:
            print(f"[ok] {group.name}: 変更なし")
            continue
        print(f"[{mode}] {group.name}: {len(changes)} 件")
        for target, old_path, new_path in changes:
            print(f"  {target}: {old_path} -> {new_path}")
        total += len(changes)
    if total:
        suffix = "" if apply else "(--apply で実際に移行します)"
        print(f"合計 {total} 件 {suffix}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="実際にコピーと書き換えを行う")
    asyncio.run(run(parser.parse_args().apply))
