# Wizmy(ウィズミィ)

キャラクター生成・チャット用のフロントエンドUIです。

## 開発状況について

このリポジトリは現在開発中です。

予告なく破壊的変更が入る可能性があります。設定ファイル、保存データ、API、UI、ディレクトリ構成、生成ロジックなどの互換性はまだ保証していません。安定版として利用する場合は、必ず必要なデータをバックアップしてください。

## テスト・lint の実行方法

開発用依存を同期する場合は、次のコマンドを実行します。

```powershell
uv sync --dev
```

全テストは次のコマンドで実行します。

```powershell
uv run pytest
```

lint と formatter の確認は次のコマンドで実行します。

```powershell
uv run ruff check .
uv run ruff format --check .
```

型チェックは次のコマンドで実行します。

```powershell
uv run mypy
```

現在は既存ファイルの一括整形を避けるため、`ruff format` の対象外ファイルを `pyproject.toml` に明記しています。新規ファイルは除外リストへ追加せず、formatter の確認対象にしてください。
