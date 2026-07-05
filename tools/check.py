"""開発用チェックをまとめて実行するスクリプト。"""

import subprocess
import sys

COMMANDS: tuple[tuple[str, ...], ...] = (
    (sys.executable, "-m", "pytest"),
    (sys.executable, "-m", "ruff", "check", "."),
    (sys.executable, "-m", "ruff", "format", "--check", "."),
    (sys.executable, "-m", "mypy"),
)


def main() -> int:
    for command in COMMANDS:
        print(f"\n$ {' '.join(command)}", flush=True)
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
