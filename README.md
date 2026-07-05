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

全チェックは次のコマンドでまとめて実行します。

```powershell
uv run python tools/check.py
```

個別に全テストを実行する場合は、次のコマンドを使います。

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

## 依存関係ファイルの更新方法

依存関係は `pyproject.toml` と `uv.lock` で管理します。`requirements.txt` は配布・互換用途の生成物として扱い、直接編集しません。

`requirements.txt` を更新する場合は、次のコマンドで uv の lock から生成してください。

```powershell
"# このファイルは uv export で生成されます。直接編集しないでください。" | Set-Content -Path requirements.txt -Encoding UTF8
uv export --no-dev --format requirements.txt --no-hashes --no-header --no-annotate | Add-Content -Path requirements.txt -Encoding UTF8
```
