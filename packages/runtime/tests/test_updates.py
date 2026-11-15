from unittest.mock import patch

import httpx
import pytest

from lms_mcp import __version__
from lms_mcp.config import Config, LMSError
from lms_mcp.updates import check_updates, repository_name


@pytest.mark.parametrize(
    "value", ["example/repo", "https://github.com/example/repo.git", "git@github.com:example/repo.git"]
)
def test_repository_normalization(value):
    assert repository_name(value) == "example/repo"


@pytest.mark.parametrize(
    "value",
    [
        "https://user:secret@github.com/a/b",
        "https://evil.org/a/b",
        "a/../x",
        "a/..",
        "https://github.com/a/b?token=x",
    ],
)
def test_repository_rejects_untrusted_urls(value):
    with pytest.raises(LMSError):
        repository_name(value)


async def test_latest_release_commit_cache_and_force(tmp_path, monkeypatch):
    monkeypatch.setenv("LMS_MCP_CHECK_UPDATES", "1")
    seen = []

    def handler(request):
        seen.append(request)
        assert request.url.host == "api.github.com"
        assert "cookie" not in request.headers and "authorization" not in request.headers
        if request.url.path.endswith("/latest"):
            return httpx.Response(200, json={"tag_name": "v0.10.0", "draft": False, "prerelease": False})
        return httpx.Response(200, json=[{"sha": "b" * 40}])

    transport = httpx.MockTransport(handler)
    with patch("lms_mcp.updates.identity", return_value=("example/repo", "a" * 40)):
        first = await check_updates(Config(tmp_path), transport=transport)
        assert first["update_available"] is True
        assert first["repository_changed"] is True
        assert first["installed_version"] == __version__
        assert (await check_updates(Config(tmp_path), transport=transport))["cached"]
        assert len(seen) == 2
        await check_updates(Config(tmp_path), force=True, transport=transport)
        assert len(seen) == 4


@pytest.mark.parametrize(
    "release",
    [None, {"tag_name": "v0.2.0"}, {"tag_name": "v99.0.0-rc1"}, {"tag_name": "v99.0.0", "prerelease": True}],
)
async def test_absent_old_or_prerelease_is_not_upgrade(tmp_path, monkeypatch, release):
    monkeypatch.setenv("LMS_MCP_CHECK_UPDATES", "1")

    def handler(request):
        if request.url.path.endswith("/latest"):
            return httpx.Response(404) if release is None else httpx.Response(200, json=release)
        return httpx.Response(200, json=[{"sha": "a" * 40}])

    result = await check_updates(
        Config(tmp_path), repository="example/repo", transport=httpx.MockTransport(handler)
    )
    assert not result["update_available"]
    assert result["latest_revision"] == "a" * 40
    assert result["repository_changed"] is None


async def test_rate_limit_and_offline_do_not_block_work(tmp_path, monkeypatch):
    monkeypatch.setenv("LMS_MCP_CHECK_UPDATES", "1")
    transport = httpx.MockTransport(lambda _: httpx.Response(403))
    result = await check_updates(Config(tmp_path), repository="example/repo", transport=transport)
    assert result["status"] == "unavailable"
    assert "update_available" not in result
    assert (await check_updates(Config(tmp_path), repository="example/repo", transport=transport))["cached"]


async def test_disabled_never_connects(tmp_path, monkeypatch):
    monkeypatch.setenv("LMS_MCP_CHECK_UPDATES", "0")
    result = await check_updates(
        Config(tmp_path),
        repository="example/repo",
        transport=httpx.MockTransport(lambda _: pytest.fail("Network disabled")),
    )
    assert result["status"] == "disabled"


async def test_unconfigured_repo_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("LMS_MCP_CHECK_UPDATES", "1")
    with patch("lms_mcp.updates.identity", return_value=(None, None)):
        assert (await check_updates(Config(tmp_path)))["status"] == "not_configured"


async def test_corrupt_cache_and_oversized_response_are_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("LMS_MCP_CHECK_UPDATES", "1")
    (tmp_path / "updates.json").write_text("[]")
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * (513 * 1024)))
    result = await check_updates(Config(tmp_path), repository="example/repo", transport=transport)
    assert result["status"] == "unavailable"


async def test_changed_install_revision_invalidates_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("LMS_MCP_CHECK_UPDATES", "1")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(404)

    with patch("lms_mcp.updates.identity", return_value=("example/repo", "a" * 40)):
        await check_updates(Config(tmp_path), transport=httpx.MockTransport(handler))
    with patch("lms_mcp.updates.identity", return_value=("example/repo", "b" * 40)):
        await check_updates(Config(tmp_path), transport=httpx.MockTransport(handler))
    assert len(requests) == 4
