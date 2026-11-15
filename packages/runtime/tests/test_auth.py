import json

import pytest

from lms_mcp.auth import AuthManager
from lms_mcp.config import AuthRequired
from lms_mcp.session import parse_cookies


async def test_failed_import_does_not_replace_working_session(store):
    def probe(_):
        raise AuthRequired("invalid")

    auth = AuthManager(store, probe=probe)
    with pytest.raises(AuthRequired):
        await auth.import_cookies(parse_cookies("session=wrong"))
    assert store.get()[0]["value"] == "test-secret"


async def test_mcp_login_only_returns_local_instruction(store):
    auth = AuthManager(store)
    result = await auth.begin()
    assert result["state"] == "local_input_required"
    assert result["command"].endswith("cu-lms-mcp login")
    assert auth.status()["login_method"] == "local_sso_cli"
    assert "test-secret" not in json.dumps(auth.status())
    assert "Ctrl+C" in auth.cancel()["message"]
    await auth.close()
