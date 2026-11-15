# ChatGPT и Claude

## ChatGPT в браузере/приложении

Для локального runtime подходит Secure MCP Tunnel: код и cookies остаются у пользователя, результаты инструментов возвращаются ChatGPT. Нужны доступ к custom MCP в ChatGPT, tunnel_id и runtime API key Platform. Туннель связывается с нужным ChatGPT workspace; компьютер и tunnel-client должны оставаться включёнными. Это отдельный пользовательский шаг после получения кода с GitHub.

1. Войди в LMS локально: `uv run cu-lms-mcp login`.
2. Создай туннель в Platform и установи официальный tunnel-client. Секрет введи локально через защищённый ввод/секрет-хранилище в `CONTROL_PLANE_API_KEY`; не помещай его в чат или отслеживаемый файл.
3. Получи команду runtime: `python3 tools/client_config.py --client chatgpt`.
4. Выполни, подставив tunnel_id и полученную команду:

```bash
tunnel-client init --sample sample_mcp_stdio_local --profile cu-lms \
  --tunnel-id YOUR_TUNNEL_ID --mcp-command 'COMMAND_FROM_CLIENT_CONFIG'
tunnel-client doctor --profile cu-lms --explain
tunnel-client run --profile cu-lms
```

5. В ChatGPT: Plugins → Add custom MCP server → Connection: Tunnel. Выбери созданный туннель и проверь `get_dashboard`.

Доступ зависит от разрешений аккаунта/workspace. Если режима Tunnel нет, один GitHub URL его не добавит. Настоящее подключение аккаунта пока не выполнено.

Источник и актуальные требования: [официальное руководство Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

## Claude Desktop

Выполни `python3 tools/client_config.py --client claude`. Добавь напечатанный объект сервера `cu-lms` в существующий `mcpServers`, не заменяя другие записи.

Конфиг обычно расположен:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`.
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`.

Полностью перезапусти клиент. Проверь наличие `get_dashboard` и вызови его. Путь установки должен оставаться доступным. Авторизацию можно пройти заранее через CLI либо через `auth_login`/`auth_status` в чате. Локальные файлы и окно браузера появляются на компьютере, где запускается MCP.

Этот вариант использует стандартный stdio и не требует установленного Codex. Реальный Claude Desktop здесь не запускался. Официальная инструкция: [подключение локального сервера](https://modelcontextprotocol.io/docs/develop/connect-local-servers).

## Claude Code

В репозитории есть `.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json`, `.mcp.json` и `skills/`:

```text
/plugin marketplace add OWNER/REPO
/plugin install cu-lms@cu-lms
```

`OWNER/REPO` заменяется адресом созданного репозитория. Для desktop-режима достаточно сгенерированной MCP-конфигурации выше. Для Claude web нужна отдельная удалённая MCP-связь; локальный конфиг туда не переносится.
