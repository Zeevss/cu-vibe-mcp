# CU LMS — плагин из GitHub

Курсы, ведомость, задания и дедлайны, LD, лонгриды, выгрузки и силлабусы ЦУ. Код и навык поставляются одним GitHub-репозиторием или ZIP релиза. Runtime входит в пакет; отдельный каталог, домен, nginx и Docker не требуются.

Портал читает локальный процесс пользователя. Cookies хранятся на его компьютере. Результаты вызовов поступают в выбранный чат. Общего сервера с пользовательскими сессиями нет.

## Установка по URL репозитория

Нужны Python 3.11+, uv и клиент с поддержкой локального MCP. После публикации репозитория замени `OWNER/REPO` на его адрес:

```bash
codex plugin marketplace add https://github.com/OWNER/REPO
codex plugin add cu-lms@cu-lms
```

Открой новый чат. Плагин включает навык и локальный MCP: для чтения учебных данных модель может вызывать инструменты без терминала. При первом запуске uv устанавливает зависимости по lock-файлу.

Из клона или ZIP GitHub Release:

```bash
python3 install.py
```

Установщик добавляет источник в Codex; сохраняй эту папку. Для самостоятельного использования CLI:

```bash
uv sync --frozen
uv run cu-lms-mcp login
uv run cu-lms-mcp import-cookie
uv run cu-lms-mcp updates --force
```

`login` находит браузер и открывает отдельное окно для ручного входа. `import-cookie` использует скрытый ввод; также доступен `--file`. Значения cookie в чат не передаются. Настройки и сессия находятся в пользовательской папке данных, отдельно от кода.

## Обычный ChatGPT

Да, локальный MCP можно подключить к обычному ChatGPT через **Secure MCP Tunnel**, если эти функции доступны аккаунту/workspace. GitHub URL служит источником установки, а для вызовов инструментов нужна работающая связь с runtime. GitHub Pages не исполняет Python/MCP.

Схема: `ChatGPT → приватный туннель → локальный MCP → портал ЦУ`. Компьютер и tunnel-client должны работать во время чата. Нужны отдельные права Platform Tunnel и custom MCP, а также runtime API key для tunnel-client. Настройка не выполняется автоматически установкой навыка.

[Пошаговое подключение ChatGPT](docs/chat-clients.md). До реального вызова в аккаунте ChatGPT интеграция считается подготовленной, а не подтверждённой end-to-end. Возможность использовать локальный плагин в desktop-приложении зависит от режима исполнения чата.

## Claude

**Claude Desktop:** склонируй репозиторий или распакуй релиз в постоянную папку и сгенерируй конфигурацию:

```bash
python3 tools/client_config.py --client claude
```

Добавь выведенную секцию `cu-lms` в `mcpServers` файла `claude_desktop_config.json`, сохранив остальные серверы, и перезапусти Claude. Генератор использует абсолютные пути и ничего сам не перезаписывает. Сам навык для работы MCP не обязателен.

**Claude Code:** репозиторий также содержит marketplace и manifest Claude:

```text
/plugin marketplace add OWNER/REPO
/plugin install cu-lms@cu-lms
```

Поддержка подготовлена на уровне конфигурации и стандартного MCP; запуск настоящего приложения Claude в этой среде не проверен. Claude в браузере также требует доступного удалённого MCP; установка desktop-конфига не подключает веб-чат.

## Меньше вызовов

По умолчанию плагин использует `serve --compact`, в котором семь инструментов:

| Инструмент | Назначение |
|---|---|
| `get_dashboard` | Курсы, активные задания, LD и сводная ведомость одним вызовом |
| `describe_methods` | Индекс либо схемы до восьми методов |
| `batch` | До 20 чтений с объединением одинаковых API-запросов |
| `auth_login`, `auth_status`, `auth_cancel` | Вход через отдельное окно браузера |
| `check_updates` | Версия релиза и состояние репозитория |

Для известных сценариев нужен один dashboard или batch. Схемы остальных операций загружаются по необходимости. Полный набор инструментов сохраняется в `serve` без `--compact`. CLI поддерживает `run --stdin`, `run --file` и `methods --name`.

## Проверка версий

На запуске `serve` и `run` проверяется GitHub; результат кешируется на 24 часа. Команда `updates --force` и MCP `check_updates(force=true)` проверяют немедленно.

- `installed_version` / `latest_version`: текущая версия и последний стабильный GitHub Release; сравнение числовое, prerelease не считается стабильным обновлением.
- `installed_revision` / `latest_revision`: commit сборки/клона и HEAD default branch.
- `repository_changed`: отличается ли известный установленный commit. Если commit неизвестен — `null`, а не выдуманный результат.
- Ошибка сети, приватный репозиторий или rate limit → `unavailable`, локальная работа продолжается.
- `LMS_MCP_CHECK_UPDATES=0` полностью отключает проверки.

Слежка выполняется при использовании и по явному запросу, без фонового демона. Ни `git pull`, ни запуск скачанного кода автоматически не выполняются. Для обновления Git-marketplace в Codex: `codex plugin marketplace upgrade cu-lms`, затем `codex plugin add cu-lms@cu-lms` и новый чат. Клон обновляй обычным проверенным git workflow.

Пока репозиторий не создан, проверка вернёт `not_configured`. После `git init` и настройки origin выполни и закоммить:

```bash
uv run python tools/configure_repository.py
```

Либо укажи `OWNER/REPO` аргументом. Это закрепляет адрес в поставляемом плагине, где `.git` может отсутствовать. Для личного переопределения есть `LMS_MCP_REPOSITORY=OWNER/REPO`. GitHub получает только запросы публичных метаданных репозитория; cookies LMS не используются.

## Выпуск на GitHub

Workflow `.github/workflows/release.yml` проверяет тесты, lint и самостоятельность пакета. При push тега `vX.Y.Z` проверяет совпадение версий/репозитория и публикует ZIP, SHA256SUMS и release.json в GitHub Releases. Существующие assets не перезаписывает.

Перед тегом обнови версии корневого проекта, runtime (`pyproject.toml`, `__init__.py`), `plugin.json`, `.codex-plugin/plugin.json`, `.claude-plugin/plugin.json` и lock-файлы. Адрес берётся из `GITHUB_REPOSITORY`, commit — из `GITHUB_SHA`. Никакой серверный хостинг не нужен.

Локальная сборка:

```bash
uv run python tools/build_release.py
```

Результат: `dist/release/cu-lms-plugin-0.3.0.zip` и распакованный `plugin/`. В ZIP только явный список исходников, manifest и lock-файлов; пользовательские данные не включаются. GitHub Release пока не опубликован — репозиторий создаётся отдельно.

## Структура и проверки

```text
packages/runtime/       Работа с порталом, CLI/MCP, версия и обновления
skills/cu-lms/          Общие инструкции для MCP-чата и локального терминала
tools/                  Сборка, клиентские конфиги, настройка репозитория, smoke-тест
.github/workflows/      Тесты и публикация тегированных релизов
.agents/plugins/        Marketplace Codex
.claude-plugin/         Marketplace и manifest Claude Code
docs/                   Исследование портала, ограничения, подключение чатов
```

```bash
uv sync --frozen
uv run pytest -q
LMS_MCP_BROWSER_TEST=1 uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python tools/smoke_release.py
```

Smoke-тест запускает собранный runtime как настоящий stdio MCP-клиент чата: initialize, discovery, схемы и batch без доступа модели к shell. Реальный аккаунт не используется. `--offline-deps` использует уже заполненный кеш uv.

[Авторизация и семантика данных](docs/local-runtime.md) · [Исследование портала](docs/portal-research.md) · [Наблюдавшийся API](docs/observed-api.md) · [Подключение чатов](docs/chat-clients.md)
