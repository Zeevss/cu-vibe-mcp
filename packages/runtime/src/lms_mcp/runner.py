"""One local process can execute a complete read-only request or a batch."""

import asyncio
import json
from copy import deepcopy

from jsonschema import Draft202012Validator

from .auth import AuthManager
from .client import LMSClient
from .config import Config, LMSError
from .session import SessionStore

# Browser authentication has an interactive CLI lifecycle; do not start it in a short-lived batch.
INTERACTIVE = {
    "auth_login",
    "auth_cancel",
    "auth_import_cookie",
    "auth_forget",
    "batch",
    "describe_methods",
    "check_updates",
}


class RequestCacheClient:
    """Deduplicate within one invocation only. A new invocation always gets fresh data."""

    def __init__(self, client):
        self.base = client
        self.store = client.store
        self.cache = {}
        self.requests = 0
        self.hits = 0

    async def get(self, path, params=None, service="lms", require_auth=True):
        # Normalize mapping order without losing repeated query parameters.
        values = sorted(params.items()) if isinstance(params, dict) else params
        key = (service, path, json.dumps(values, sort_keys=True), require_auth)
        if key not in self.cache:
            self.requests += 1
            self.cache[key] = asyncio.create_task(self.base.get(path, params, service, require_auth))
        else:
            self.hits += 1
        try:
            return deepcopy(await self.cache[key])
        except Exception:
            self.cache.pop(key, None)
            raise


class LocalRunner:
    def __init__(self, config=None, client=None):
        from .server import create_server

        self.config = config or Config.from_env()
        self.client = RequestCacheClient(client or LMSClient(SessionStore(self.config.data_dir)))
        self.auth = AuthManager(self.client.store)
        self.server = create_server(self.config, client=self.client, auth=self.auth)

    async def methods(self):
        return {
            tool.name: tool.model_dump(mode="json", exclude_none=True)
            for tool in await self.server.list_tools()
            if tool.name not in INTERACTIVE
        }

    async def run(self, request):
        if not isinstance(request, dict):
            raise LMSError("Ожидается JSON-объект запроса")
        calls = request.get("calls") if "calls" in request else [request]
        if not isinstance(calls, list) or not 1 <= len(calls) <= 20:
            raise LMSError("В одном запросе должно быть от 1 до 20 вызовов")
        methods = await self.methods()
        # Validate the whole plan before performing any request or writing files.
        validated = []
        identifiers = set()
        for index, call in enumerate(calls):
            if not isinstance(call, dict):
                raise LMSError("Каждый вызов должен быть объектом")
            name, params = call.get("method"), call.get("params", {})
            identifier = call.get("id", str(index))
            if not isinstance(identifier, str) or len(identifier) > 100 or identifier in identifiers:
                raise LMSError("ID вызовов должны быть уникальными строками длиной до 100 символов")
            identifiers.add(identifier)
            if not isinstance(name, str) or name not in methods:
                raise LMSError("Неизвестный метод или метод недоступен для пакетного исполнения")
            schema = methods[name]["inputSchema"]
            if (
                not isinstance(params, dict)
                or set(params) - set(schema.get("properties", {}))
                or not Draft202012Validator(schema).is_valid(params)
            ):
                raise LMSError(f"Параметры {name} не соответствуют схеме; используйте methods")
            validated.append((identifier, name, params))
        results = []
        try:
            for identifier, name, params in validated:
                try:
                    value = await self.server.call_tool(name, params)
                    blocks = value[0] if isinstance(value, tuple) else value
                    payload = json.loads(blocks[0].text)
                    results.append({"id": identifier, "method": name, "ok": True, "result": payload})
                except Exception as error:
                    # Only our credential-free error type may be propagated to the caller.
                    from mcp.server.fastmcp.exceptions import ToolError

                    message = (
                        str(error) if isinstance(error, (LMSError, ToolError)) else "Ошибка локального метода"
                    )
                    results.append({"id": identifier, "method": name, "ok": False, "error": message})
                    if request.get("stop_on_error", False):
                        break
            return {
                "ok": all(item["ok"] for item in results),
                "results": results,
                "metrics": {"api_requests": self.client.requests, "cache_hits": self.client.hits},
            }
        finally:
            await self.auth.close()


async def batch(config, client, calls):
    return await LocalRunner(config, client).run({"calls": calls})
