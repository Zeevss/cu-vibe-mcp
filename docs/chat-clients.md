# Подключение обычного ChatGPT

Код с [GitHub](https://github.com/Zeevss/cu-vibe-mcp) выполняется на твоём компьютере. Secure MCP Tunnel связывает его с ChatGPT без входящего публичного порта. GitHub URL служит адресом исходников, а не MCP endpoint.

## Подготовка

1. Установи зависимости и выполни `login` из [README](../README.md). CLI и туннель должны работать от одного пользователя ОС с одинаковым `LMS_MCP_DATA_DIR`, если он задан.
2. В Platform создай туннель и свяжи с нужным ChatGPT workspace. Создание требует Tunnels Read + Manage, запуск/выбор — Read + Use. Доступ к custom MCP в ChatGPT регулируется отдельно.
3. Скачай официальный tunnel-client из ссылки в Platform или [официального latest release](https://github.com/openai/tunnel-client/releases/latest), выбрав доступную сборку для своей ОС/архитектуры. Убедись, что команда есть в PATH: `tunnel-client help quickstart`.
4. Передай runtime API key в окружение `CONTROL_PLANE_API_KEY` локально, через скрытый ввод или секрет-хранилище. Не вставляй его в чат, аргументы команд или Git. Ключ нужен процессу туннеля; это не пароль ЦУ.

Актуальные требования и доступность: [официальное руководство OpenAI](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels). Если Tunnel недоступен аккаунту или нет сборки tunnel-client для твоей платформы, установка одного навыка этого не исправит.

## macOS / Linux

В терминале из папки репозитория или распакованного релиза, где уже настроен ключ:

```bash
mcp_command="$(uv run --project packages/runtime --frozen python tools/client_config.py --client chatgpt)"
tunnel-client init --sample sample_mcp_stdio_local --profile cu-lms --tunnel-id YOUR_TUNNEL_ID --mcp-command "$mcp_command"
tunnel-client doctor --profile cu-lms --explain
tunnel-client run --profile cu-lms
```

## Windows PowerShell

```powershell
$mcpCommand = uv run --project packages/runtime --frozen python tools/client_config.py --client chatgpt
tunnel-client init --sample sample_mcp_stdio_local --profile cu-lms --tunnel-id YOUR_TUNNEL_ID --mcp-command "$mcpCommand"
tunnel-client doctor --profile cu-lms --explain
tunnel-client run --profile cu-lms
```

`YOUR_TUNNEL_ID` — ID созданного туннеля. Генератор печатает абсолютный путь к uv и runtime с учётом ОС, ничего не меняя в настройках. Не закрывай процесс `run` во время работы в чате.

## В ChatGPT

Plugins → кнопка «+» → Add custom MCP server → Connection: Tunnel. Выбери тот же tunnel_id, настрой требуемую аутентификацию подключения и создай плагин. Если туннель не виден, проверь workspace association и права Read + Use.

Первый вызов — `get_dashboard`. Если сессии LMS нет, `auth_login` выдаст команду локального входа. Выполни её у себя; пароль и код спрашивает локальная программа. После завершения сообщи об этом в чат — `auth_status(validate=true)` проверит сессию. Постоянный опрос статуса во время ввода не требуется. `auth_cancel` только объясняет Ctrl+C; он не останавливает независимый CLI-процесс.

Основные инструкции встроены в MCP. Подключение туннеля не устанавливает автоматически файл `skills/cu-lms/SKILL.md`. Передача этого файла в чат также не заменяет настройку MCP.

Реальный вызов из ChatGPT с пользовательским аккаунтом здесь ещё не проверен. Успешный локальный stdio smoke-тест подтверждает протокол runtime, но не доступность туннеля конкретному аккаунту.
