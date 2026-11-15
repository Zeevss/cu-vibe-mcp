import asyncio
import json
from urllib.parse import urlsplit

import httpx

from .config import ORIGINS, AuthRequired, LMSError
from .session import SessionStore, cookie_jar, jar_cookies


class LMSClient:
    def __init__(self, store: SessionStore, transport=None):
        self.store = store
        self.transport = transport
        self.locks = {s: asyncio.Lock() for s in ORIGINS}

    async def get(self, path: str, params=None, service="lms", require_auth=True):
        if service not in ORIGINS:
            raise LMSError("Неизвестный сервис")
        if not path.startswith("/api/") or path.startswith("//") or urlsplit(path).netloc:
            raise LMSError("Разрешены только внутренние маршруты API")
        async with self.locks[service]:
            cookies = self.store.get(service)
            if require_auth and not cookies:
                raise AuthRequired(
                    "Нужен вход: auth_login или cu-lms-mcp login; альтернатива — auth import-cookie"
                )
            async with httpx.AsyncClient(
                base_url=ORIGINS[service],
                cookies=cookie_jar(cookies, service),
                follow_redirects=False,
                timeout=30,
                trust_env=False,
                transport=self.transport,
            ) as client:
                try:
                    async with client.stream("GET", path, params=params) as response:
                        if response.status_code in (301, 302, 303, 307, 308, 401):
                            raise AuthRequired(
                                "Сессия истекла или не принята. Повторите браузерный вход/импорт cookie."
                            )
                        if response.status_code == 403:
                            raise LMSError("Доступ запрещён (403): проверьте права и актуальность сессии")
                        if response.status_code == 404:
                            raise LMSError("Объект не найден или API портала изменился (404)")
                        if response.status_code == 204:
                            return None
                        if response.status_code != 200:
                            raise LMSError(f"API временно недоступен (HTTP {response.status_code})")
                        if "json" not in response.headers.get("content-type", ""):
                            raise AuthRequired("API вернул страницу вместо JSON; повторите вход")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 20 * 1024 * 1024:
                                raise LMSError("Ответ API превышает 20 МиБ")
                        try:
                            data = json.loads(body)
                        except ValueError:
                            raise LMSError("API вернул некорректный JSON") from None
                        if cookies:
                            # Preserve Set-Cookie rotations and deletions without logging their values.
                            rotated = jar_cookies(client.cookies, service)
                            if rotated != cookies:
                                self.store.rotate(cookies, rotated, service)
                        return data
                except httpx.HTTPError:
                    raise LMSError("Сетевая ошибка при обращении к порталу") from None
