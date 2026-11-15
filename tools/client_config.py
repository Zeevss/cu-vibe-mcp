#!/usr/bin/env python3
"""Print local MCP configuration for chat clients; never edit existing settings."""

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def launch_command(root=ROOT):
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("Нужен uv в PATH")
    return [
        str(Path(uv).resolve()),
        "run",
        "--directory",
        str(Path(root).resolve() / "packages/runtime"),
        "--frozen",
        "--no-dev",
        "cu-lms-mcp",
        "serve",
        "--compact",
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", choices=["claude", "chatgpt"], default="claude")
    args = parser.parse_args()
    try:
        argv = launch_command()
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    if args.client == "claude":
        print(json.dumps({"mcpServers": {"cu-lms": {"command": argv[0], "args": argv[1:]}}}, indent=2))
    else:
        # Paste as the value of --mcp-command in tunnel-client init; no credentials included.
        print(subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
