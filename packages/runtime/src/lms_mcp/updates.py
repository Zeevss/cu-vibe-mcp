"""Bounded, opt-out GitHub version checks. Never install or execute remote code."""

import asyncio
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from filelock import FileLock

from . import __version__
from .config import LMSError

TTL = 24 * 60 * 60


def repository_name(value):
    value = value.strip()
    if value.startswith("git@github.com:"):
        value = value[len("git@github.com:") :]
    elif value.startswith("https://"):
        parsed = urlsplit(value)
        if parsed.netloc != "github.com" or parsed.query or parsed.fragment:
            raise LMSError("Нужен GitHub owner/repository или HTTPS URL без credentials")
        value = parsed.path.strip("/")
    if value.endswith(".git"):
        value = value[:-4]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", value):
        raise LMSError("Нужен GitHub owner/repository")
    if value.split("/")[1] in {".", ".."}:
        raise LMSError("Некорректное имя репозитория")
    return value


def git_value(*args):
    root = Path(__file__).resolve().parents[4]
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=2)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def identity():
    info = json.loads(Path(__file__).with_name("repository.json").read_text())
    repo = (
        os.getenv("LMS_MCP_REPOSITORY") or info.get("repository") or git_value("remote", "get-url", "origin")
    )
    revision = info.get("revision") or git_value("rev-parse", "HEAD")
    return (repository_name(repo) if repo else None), revision


def version_tuple(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value or "")
    return tuple(map(int, match.groups())) if match else None


async def fetch_status(repository, revision, transport=None):
    base = f"https://api.github.com/repos/{repository}"
    result = {
        "status": "ok",
        "repository": repository,
        "installed_version": __version__,
        "installed_revision": revision,
        "latest_version": None,
        "update_available": False,
        "latest_revision": None,
        "repository_changed": None,
    }
    async with httpx.AsyncClient(
        transport=transport,
        timeout=3,
        follow_redirects=False,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "cu-lms-mcp-version-check"},
    ) as client:

        async def read(suffix):
            async with client.stream("GET", base + suffix) as response:
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                content = bytearray()
                async for block in response.aiter_bytes():
                    content.extend(block)
                    if len(content) > 512 * 1024:
                        raise ValueError("Oversized version response")
                return json.loads(content)

        release, commits = await asyncio.gather(read("/releases/latest"), read("/commits?per_page=1"))
    if isinstance(release, dict) and not release.get("draft") and not release.get("prerelease"):
        tag = release.get("tag_name")
        latest = version_tuple(tag)
        if latest:
            result["latest_version"] = tag
            result["update_available"] = latest > version_tuple(__version__)
            result["release_url"] = f"https://github.com/{repository}/releases/tag/{tag}"
    if isinstance(commits, list) and commits and isinstance(commits[0], dict):
        sha = commits[0].get("sha", "")
        if re.fullmatch(r"[0-9a-f]{40}", sha):
            result["latest_revision"] = sha
            result["repository_changed"] = sha != revision if revision else None
    if release is None and commits is None:
        result["status"] = "unavailable"
    return result


async def check_updates(config, force=False, repository=None, transport=None):
    if repository:
        repo, revision = repository_name(repository), None
    else:
        repo, revision = identity()
    base = {"installed_version": __version__, "repository": repo, "installed_revision": revision}
    if os.getenv("LMS_MCP_CHECK_UPDATES", "1").lower() in {"0", "false", "no"}:
        return {**base, "status": "disabled"}
    if not repo:
        return {
            **base,
            "status": "not_configured",
            "message": "После создания репозитория настройте origin или LMS_MCP_REPOSITORY=owner/repo",
        }
    cache = config.data_dir / "updates.json"
    try:
        previous = json.loads(cache.read_text())
        if (
            isinstance(previous, dict)
            and not force
            and previous.get("repository") == repo
            and previous.get("installed_version") == __version__
            and previous.get("installed_revision") == revision
            and 0 <= time.time() - previous["checked_at"] < TTL
        ):
            return {**previous, "cached": True}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        result = await asyncio.wait_for(fetch_status(repo, revision, transport), timeout=4)
    except (httpx.HTTPError, ValueError, TypeError, TimeoutError):
        result = {
            **base,
            "status": "unavailable",
            "message": "GitHub недоступен; локальная работа продолжается",
        }
    result["checked_at"] = time.time()
    try:
        config.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with FileLock(str(cache) + ".lock", timeout=1):
            with tempfile.NamedTemporaryFile(mode="w", dir=config.data_dir, delete=False) as handle:
                json.dump(result, handle)
                staged = Path(handle.name)
            staged.replace(cache)
    except (OSError, TimeoutError):
        pass
    return result


async def notify_update(config):
    import sys

    try:
        result = await check_updates(config)
        if result.get("update_available"):
            print(f"cu-lms: доступна {result['latest_version']}: {result['release_url']}", file=sys.stderr)
    except (LMSError, OSError, ValueError):
        # Update metadata must never prevent a local MCP session from starting.
        pass
