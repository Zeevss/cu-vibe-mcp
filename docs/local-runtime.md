# Локальный runtime и данные

MCP-сервер для `my.centraluniversity.ru`, работающий на твоём компьютере через **stdio**. Реализованы курсы, ведомость, задания/сроки/LD, лонгриды, выгрузка файлов, результаты завершённых тестов и чтение силлабусов Note. Этот режим не открывает HTTP-порт. Основной вариант поставки — плагин из GitHub, описанный в корневом README.

## Установка и SSO-вход

Из корня проекта на Windows, macOS или Linux:

```text
uv sync --project packages/runtime --frozen --no-dev
uv run --project packages/runtime --frozen cu-lms-mcp login
uv run --project packages/runtime --frozen cu-lms-mcp status --validate
```

`login` читает шаги SSO ЦУ через HTTP и спрашивает email, пароль и код в локальном терминале со скрытым вводом. Браузер и WebDriver для входа не используются; `login --browser` удалён. `/resend` на шаге OTP запрашивает новый код; Ctrl+C отменяет попытку. CAPTCHA, восстановление пароля и настройка MFA требуют действий на сайте. Подробности и проверенные границы — [SSO](sso.md).

В MCP `auth_login` возвращает инструкцию, а не запускает вход. После завершения CLI вызывается `auth_status(validate=true)`. MCP не принимает секреты и не управляет самостоятельным процессом CLI; `auth_cancel` объясняет, как отменить его локально. Папка `LMS_MCP_DATA_DIR` должна совпадать у CLI и MCP.

Selenium и поиск браузеров остаются только для `get_syllabus`: Note требует рендеринга. При проблемах выбери браузер параметром `browser` этого метода или настрой WebDriver. Браузеры/драйверы пользователя автоматически не изменяются.

## Вход через cookie

Скрытый ввод в терминале (не попадает в историю команд):

```bash
uv run cu-lms-mcp import-cookie
```

Можно вставить полную строку `Cookie` из запроса портала в DevTools → Network → Request Headers. Для разбитой на части cookie нужны **все части**. Поддерживаются:

- строка `Cookie: name=value; name2=value2` или без префикса `Cookie:`;
- JSON-массив cookies с полями `name`, `value`, `domain`, `path`, `expires`/`expiry`;
- объект `{"cookies": [...]}` (например, storage state);
- Netscape cookie-файл, включая `#HttpOnly_`.

Импорт файла и stdin:

```bash
uv run cu-lms-mcp import-cookie --file /absolute/path/to/cookies.json
uv run cu-lms-mcp import-cookie --stdin < /absolute/path/to/cookies.txt
```

В MCP: `auth_import_cookie(cookie_file="/absolute/path/to/cookies.json")`. Сами секретные значения передавать в чат/аргументы инструмента не требуется. Неудачная проверка не заменяет прежнюю рабочую сессию.

Сессия Note отдельная. Если силлабус закрыт, можно импортировать cookies именно `note.cu.ru`:

```bash
uv run cu-lms-mcp import-cookie --service note --file /absolute/path/to/note-cookies.json
```

Для Note проверяются формат и домен; успешное сохранение не означает подтверждённого входа. Реальная доступность проверяется чтением силлабуса. Cookies LMS не отправляются в Note и файловое хранилище.

## Подключение к MCP-клиенту

Получить конфигурацию с абсолютным путём к текущему Python:

```bash
uv run cu-lms-mcp config
```

Команда печатает объект `mcpServers`, подходящий клиентам с JSON-конфигурацией stdio. Для клиента с другим форматом используй те же `command`, `args` и `env`.

Пример для текущего каталога (Linux/macOS):

```json
{
  "mcpServers": {
    "cu-lms": {
      "command": "/home/zevsus/Projects/LMS_MCP/.venv/bin/python",
      "args": ["-m", "lms_mcp", "serve"]
    }
  }
}
```

На Windows путь к Python — `.venv\\Scripts\\python.exe`. Альтернативная команда: `uv --directory /absolute/path/to/LMS_MCP run --frozen cu-lms-mcp serve`. Не запускай сервер как фоновый HTTP-сервис: stdio-процесс запускает и останавливает сам MCP-клиент. В stdout сервера идёт только протокол MCP; сообщения CLI используются отдельными командами.

## Инструменты

| Инструмент | Результат |
|---|---|
| `get_dashboard` | Курсы, активные задания, LD и ведомость одним вызовом |
| `batch` | До 20 методов за запуск с устранением повторных API-чтений |
| `list_browsers` | Установленные браузеры и пути |
| `auth_login`, `auth_status`, `auth_cancel` | Инструкция локального SSO-входа, сессия и подсказка отмены |
| `auth_import_cookie`, `auth_forget` | Импорт/удаление локальной сессии |
| `list_courses` | Актуальные/архивные курсы, поиск, пагинация |
| `get_course` | Темы, лонгриды, прогресс, ближайшие сроки, ссылки |
| `get_gradebook` | Сводка или детальная ведомость с весами, средними, баллами и блокерами |
| `get_academic_record` | Электронная зачётка |
| `list_assignments` | Статусы, курс, архивность курса, личные дедлайны, баллы и LD |
| `get_assignment` | Условие, внешние ссылки, решение, история событий |
| `get_late_days` | Баланс LD и данные переноса выбранной работы |
| `get_longread` | Упорядоченные блоки, Markdown, вложения и упражнения |
| `get_quiz_result` | Только оценённый тест: вопросы/ответы, результат и попытки |
| `export_material` | Локальный файл и извлечённый текст PDF/ноутбука/текста |
| `get_syllabus` | Текст и таблицы Note через headless-браузер |

Примеры параметров:

```text
list_courses(archived=true)
get_gradebook(course_id=1127)
list_assignments(deadline_from="2026-11-15", deadline_before="2026-11-23", course_archived=false)
list_assignments(states=["evaluated", "failed"], offset=0, limit=50)
get_late_days(task_id=2289310)
get_longread(longread_id=19567)
export_material(longread_id=19567, material_id=<id файлового блока из get_longread>)
get_syllabus(course_id=1127)
```

Диапазон сроков — `[from, before)`. Даты без зоны трактуются в Europe/Moscow; ответы содержат исходные ISO-даты и локальное отображение. По умолчанию `list_assignments` возвращает активные состояния. Пагинация по `offset`/`limit` происходит после фильтрации; в ответе есть `total_count` и `next_offset`.

## Семантика и ограничения

- Официальные средние и итоги берутся с сервера LMS. Среднее по уже оценённым работам может отличаться от среднего LMS по плановому объёму. `null` оценки сохраняется.
- Архивность курса и завершённость работы независимы. «Решение прикреплено» не заменяется на «Сдано».
- LD: баланс, уже потраченные дни и флаги разрешения возвращаются отдельно. `can_extend_now=null`: полная серверная допустимость нового переноса не установлена.
- Текст условия может вести на внешний Drive. Внешние условия автоматически не скачиваются; MCP возвращает ссылку и встроенное описание.
- Силлабус читается отдельно от ведомости. Для пустой статьи, отсутствия доступа или изменения вёрстки возвращается понятная ошибка. Политики и пороги не извлекаются в выдуманную универсальную формулу.
- Выгрузка ограничена 50 МиБ и наблюдавшимся S3-хостом портала. URL подписанной ссылки не выводится. PDF без текстового слоя требует OCR, которого пока нет. Ноутбуки не исполняются, читаются только исходники ячеек.
- Комментарии доступны в истории событий в том объёме, который возвращает сервер. Отдельный chat API, расписание, посещаемость и уведомления пока не подключены к инструментам.
- Сервер не отправляет решения, не запускает тесты, не меняет LD, не регистрирует на события и не меняет учебные данные.
- Частный API может меняться. Успешные тесты на фикстурах не заменяют проверку в реальном аккаунте.

## Локальные данные

Папка определяется `platformdirs`: обычно `~/.local/share/cu-lms-mcp` на Linux, `~/Library/Application Support/cu-lms-mcp` на macOS, локальная папка приложения на Windows. Переопределение: `LMS_MCP_DATA_DIR=/absolute/path`.

`session.json` содержит cookies в открытом виде. На POSIX папка имеет права `0700`, файл — `0600`; запись атомарная, с межпроцессной блокировкой. Сессия перечитывается перед запросами: CLI-импорт можно использовать при уже запущенном MCP. Ротация cookies старого запроса не перезаписывает более новый вход. На Windows используются права текущего профиля ОС; отдельное шифрование/DPAPI пока не реализовано.

Скачанные материалы находятся в `downloads/` этой папки. Сессия и загрузки не пишутся в репозиторий. Просроченная/непринятая сессия требует нового входа; OIDC refresh token отдельно не сохраняется.

```bash
uv run cu-lms-mcp logout
uv run cu-lms-mcp logout --service note
```

Это удаляет локальную сессию без выхода на сайте. Полную очистку загруженных материалов выполняй удалением соответствующей папки `downloads`.

## Проверка разработки

```bash
uv sync --frozen
uv run pytest -q
uv run ruff check packages/runtime/src packages/runtime/tests
```

Тесты проверяют HTTP SSO на синтетических формах, границы дат, LD/null, ротацию сессии, изоляцию источников, выгрузку и настоящий обмен MCP по stdio. Реальные пароли/cookies не используются.

Исторические проверки прежней реализации — в [implementation.md](implementation.md), текущие границы SSO — в [sso.md](sso.md).

## Исследование портала

- [Карта функций и особенности данных](portal-research.md)
- [Наблюдавшийся частный API](observed-api.md)
- [Исходное предложение интеграции](mcp-proposal.md)

Реализация опирается на [официальный MCP Python SDK v1](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x), [Selenium cookies](https://www.selenium.dev/documentation/webdriver/interactions/cookies/) и [Selenium Manager](https://www.selenium.dev/documentation/selenium_manager/).

## Браузер для силлабусов Note

Только `get_syllabus` использует Selenium. Например, при несовместимых Chrome/chromedriver можно выбрать `get_syllabus(course_id=..., browser="chromium")`. Режим `auto` предпочитает совместимую пару. Если локального драйвера нет, Selenium Manager попытается загрузить подходящий, не меняя системные бинарники. Для первой загрузки нужен доступ к источнику драйверов. Команда `browsers` показывает найденные версии. Это не относится к новому `login`.
