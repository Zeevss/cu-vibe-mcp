#!/usr/bin/env python3
"""Persist the public repository identity before committing/publishing a plugin."""

import argparse
import json
import subprocess
from pathlib import Path

from lms_mcp.updates import repository_name

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("repository", nargs="?", help="owner/repo; default: Git origin")
args = parser.parse_args()
value = (
    args.repository
    or subprocess.check_output(["git", "-C", str(ROOT), "remote", "get-url", "origin"], text=True).strip()
)
repo = repository_name(value)
(ROOT / "packages/runtime/src/lms_mcp/repository.json").write_text(
    json.dumps({"repository": repo, "revision": None}, indent=2) + "\n"
)
print("Repository:", repo)
