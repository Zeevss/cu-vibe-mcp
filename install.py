#!/usr/bin/env python3
"""Install this repository/release as a Codex plugin."""

import shutil
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    codex = shutil.which("codex")
    if not codex:
        print("Нужен Codex CLI. Для Claude Desktop: python tools/client_config.py", file=sys.stderr)
        return 1
    subprocess.run([codex, "plugin", "marketplace", "add", str(root), "--json"], check=True)
    subprocess.run([codex, "plugin", "add", "cu-lms@cu-lms", "--json"], check=True)
    print("Плагин установлен. Откройте новый чат. Нужны Python 3.11+ и uv.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
