import json
import os
import sys
from datetime import timedelta

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from lms_mcp.config import Config
from lms_mcp.server import create_server


async def test_tools_through_server_preserve_contract(make_client, tmp_path):
    client = make_client(
        lambda r: httpx.Response(200, json={"lateDaysBalance": 24, "email": "should-not-be-returned"})
    )
    server = create_server(Config(tmp_path), client=client)
    tools = await server.list_tools()
    assert len(tools) >= 17
    assert {"get_dashboard", "batch"}.issubset({tool.name for tool in tools})
    by_name = {tool.name: tool for tool in tools}
    assert by_name["get_gradebook"].annotations.readOnlyHint is True
    assert by_name["auth_login"].annotations.readOnlyHint is False
    result = await server.call_tool("get_late_days", {})
    # SDK versions can return just blocks or (blocks, structuredContent).
    blocks = result[0] if isinstance(result, tuple) else result
    payload = json.loads(blocks[0].text)
    assert payload["data"]["balance"] == 24
    assert "should-not-be-returned" not in json.dumps(payload)


async def test_real_stdio_initialization_discovery_and_error(tmp_path):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "lms_mcp", "serve"],
        env={**os.environ, "LMS_MCP_DATA_DIR": str(tmp_path / "fresh-session")},
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=10)) as session:
            initialized = await session.initialize()
            assert initialized.serverInfo.name == "cu-lms"
            tools = await session.list_tools()
            assert "get_syllabus" in {tool.name for tool in tools.tools}
            status = await session.call_tool("auth_status", {})
            assert not status.isError
            payload = json.loads(status.content[0].text)
            assert payload["session"]["has_session"] is False
            failure = await session.call_tool("list_courses", {})
            assert failure.isError
            assert "auth_login" in failure.content[0].text
            assert "Traceback" not in failure.content[0].text


async def test_compact_chat_client_can_discover_and_execute_without_shell(make_client, tmp_path):
    client = make_client(lambda _: httpx.Response(200, json={"lateDaysBalance": 24}))
    server = create_server(Config(tmp_path), client=client, compact=True)
    assert {tool.name for tool in await server.list_tools()} == {
        "get_dashboard",
        "batch",
        "describe_methods",
        "auth_login",
        "auth_status",
        "auth_cancel",
        "check_updates",
    }
    schemas = await server.call_tool("describe_methods", {"names": ["get_late_days"]})
    blocks = schemas[0] if isinstance(schemas, tuple) else schemas
    assert "inputSchema" in json.loads(blocks[0].text)["get_late_days"]
    result = await server.call_tool("batch", {"calls": [{"method": "get_late_days"}]})
    blocks = result[0] if isinstance(result, tuple) else result
    data = json.loads(blocks[0].text)
    assert data["ok"]
    assert data["results"][0]["result"]["data"]["balance"] == 24
