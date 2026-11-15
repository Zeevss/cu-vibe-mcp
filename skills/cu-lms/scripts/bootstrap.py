#!/usr/bin/env python3
"""Run the runtime bundled in the GitHub checkout or installed plugin."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

COMMANDS = {
    "run",
    "methods",
    "login",
    "import-cookie",
    "status",
    "logout",
    "browsers",
    "serve",
    "updates",
    "config",
}


def command(args, root=None):
    root = Path(root) if root else Path(__file__).resolve().parents[3]
    project = root / "packages/runtime"
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("Нужен uv: https://docs.astral.sh/uv/getting-started/installation/")
    if not (project / "uv.lock").is_file():
        raise RuntimeError("Нужен полный плагин/репозиторий с packages/runtime, а не отдельный SKILL.md")
    if not args or args[0] not in COMMANDS:
        raise RuntimeError("Команды: " + ", ".join(sorted(COMMANDS)))
    return [uv, "run", "--directory", str(project), "--frozen", "--no-dev", "cu-lms-mcp", *args]


def main():
    try:
        # uv and the runtime keep diagnostics on stderr; stdout stays valid MCP/JSON.
        argv = command(sys.argv[1:] or ["serve"])
        if os.name != "nt":
            os.execv(argv[0], argv)
        return subprocess.call(argv)
    except (RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
