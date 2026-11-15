#!/usr/bin/env python3
"""Verify the bundled plugin as a real stdio chat client, without portal credentials."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

from build_release import build
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def exercise(bootstrap, env):
    parameters = StdioServerParameters(
        command=sys.executable, args=[str(bootstrap), "serve", "--compact"], env=env
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=60)) as session:
            await session.initialize()
            assert len((await session.list_tools()).tools) == 7
            schema = await session.call_tool("describe_methods", {"names": ["get_late_days"]})
            assert "get_late_days" in json.loads(schema.content[0].text)
            result = await session.call_tool("batch", {"calls": [{"method": "get_late_days"}]})
            assert not json.loads(result.content[0].text)["ok"]
            assert not (await session.call_tool("check_updates", {})).isError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-deps", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="cu-lms-bundle-") as temporary:
        root = Path(temporary)
        build(root / "release", "example/repo", "a" * 40)
        bootstrap = root / "release/plugin/skills/cu-lms/scripts/bootstrap.py"
        env = {**os.environ, "LMS_MCP_DATA_DIR": str(root / "private"), "LMS_MCP_CHECK_UPDATES": "0"}
        if args.offline_deps:
            env["UV_OFFLINE"] = "1"
        result = subprocess.run(
            [sys.executable, str(bootstrap), "methods", "--name", "get_dashboard"],
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr
        assert "get_dashboard" in json.loads(result.stdout)
        asyncio.run(exercise(bootstrap, env))
        print(
            "PASS: bundled runtime, CLI, stdio chat discovery, schemas, batch and updates; portal not contacted."
        )


if __name__ == "__main__":
    main()
