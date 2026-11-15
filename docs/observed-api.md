# Наблюдавшийся API

Источник: сетевые ответы, полученные браузером при обычной навигации авторизованного пользователя 2026-11-15. Это обратное описание частного API интерфейса, а не официальная спецификация и не гарантия стабильности.

Базовый origin: `https://my.centraluniversity.ru`.

В этом проходе фиксировались прежде всего `Network.responseReceived` и тела выбранных ответов. HTTP-методы и схемы заголовков систематически не сохранялись: приведённые ниже URL — наблюдавшиеся запросы чтения, но не готовая проверенная OpenAPI-спецификация. Для `content/download-link` в продолжении подтверждены GET и параметры `filename`, `version`. Запросы изменения не выполнялись.

Обозначения: **ответ изучен** — прочитано тело JSON; **маршрут наблюдался** — подтверждены URL/успешный ответ, полная схема не изучена.

## Учебное ядро

Все перечисленные ответы имели статус 200, если не указано иное.

| Путь | Статус исследования | Назначение |
|---|---|---|
| `/api/micro-lms/courses/student?limit=20&offset=0&state=published` | Ответ изучен | Каталог актуальных курсов; `items`, `paging` |
| `/api/micro-lms/courses/student/count` | Маршрут наблюдался | Счётчики курсов; меню показывает 12 актуальных, 27 архивных |
| `/api/micro-lms/courses/1127` | Маршрут наблюдался | Метаданные курса |
| `/api/micro-lms/courses/1127/overview` | Ответ изучен | Курс, настройки, блокер, темы и лонгриды |
| `/api/micro-lms/themes/10010` | Ответ изучен | Название/публикация/порядок темы |
| `/api/micro-lms/longreads/43826` | Ответ изучен | Метаданные лонгрида |
| `/api/micro-lms/longreads/43826/materials?limit=10000` | Ответ изучен | Блок задания: описание, упражнение, активность, taskId |
| `/api/micro-lms/longreads/19567/materials?limit=10000` | Ответ изучен | HTML-блоки и файлы учебных материалов |
| `/api/micro-lms/tasks/2289310` | Ответ изучен | Полная персональная карточка работы |
| `/api/micro-lms/tasks/student?state=inProgress&state=backlog&state=submitted&state=review&state=reworking` | Ответ и пример элемента изучены | Общий список активных работ, включая архивные курсы |
| `/api/micro-lms/tasks/student?state=inProgress&state=backlog&state=submitted&state=review&state=reworking&sortProperty=deadline&sortDirection=1` | Маршрут наблюдался | Вариант списка с сортировкой |
| `/api/micro-lms/deadlines?limit=1&courseId=1127` | Ответ изучен | Ближайшая работа курса |
| `/api/micro-lms/courses/1127/student/progress` | Ответ изучен | Точный накопленный балл и оставшийся потенциал |
| `/api/micro-lms/performance/student?isArchived=false` | Маршрут наблюдался | Сводная ведомость курсов |
| `/api/micro-lms/courses/1127/exercises` | Маршрут наблюдался | Упражнения курса для сопоставления ведомости |
| `/api/micro-lms/courses/1127/activities` | Ответ изучен | Определения активностей, веса, плановое количество, пороги, LD |
| `/api/micro-lms/courses/1127/activities-performance` | Ответ изучен | Серверный расчёт средних и итогов по активностям |
| `/api/micro-lms/courses/1127/student-performance` | Ответ изучен | Персональные баллы работ и сработавшие блокеры |
| `/api/micro-lms/gradebook` | Маршрут наблюдался, UI изучен | Электронная зачётка |
| `/api/micro-lms/content/download-link?filename=...&version=...` | GET, ответ изучен | 200, `{url: string}`; открытие PDF в отдельной вкладке; локальная выгрузка не подтверждена |
| `/api/micro-lms/polls/longread/43826` | 204, маршрут наблюдался | Опрос материала; пустой ответ в выбранном примере |
| `/api/micro-lms/polls/longread/19567` | 204, маршрут наблюдался | Опрос материала; пустой ответ в выбранном примере |

## Подтверждённые формы данных

### Каталог

```text
{
  items: [{
    id, name, state, publishDate, publishedAt,
    participationType, commitLevel, subjectId, isArchived, category,
    settings: {
      skillLevel, isSkillLevelEnabled,
      syllabusUrl, timeChannelUrl, normalizationScore
    },
    blocker
  }],
  paging: { limit, offset, totalCount }
}
```

У всех 12 элементов прочитанного каталога `participationType=null`. Не считать это доказательством отсутствия типа участия — другие страницы его отображают.

### Дерево курса

```text
{
  id, name, isArchived, state, publishDate, publishedAt, settings,
  blocker: { enabled, enableAt, score },
  themes: [{ id, name, order, state, publishDate, publishedAt, longreads: [...] }]
}
```

Дерево тем подтверждено. Полная схема вложенного элемента `longreads` отдельно не зафиксирована.

### Материалы

Обёртка: `{items: [...], paging: {limit, offset, totalCount}}`.

Наблюдавшиеся варианты:

```text
Текст:
  discriminator="markdown", type="markdown", viewType="ngxMarkdown"
  viewContent = JSON-строка { value: HTML, isTuiEditor: true }
  id, order, state, publishDate, publishedAt

Файл:
  discriminator="file", type="content", viewType="file"
  filename, version, length, mediaType
  content: {name, filename, version, length, mediaType}
  id, order, state, publishDate, publishedAt

Упражнение:
  discriminator="coding", type="coding", viewType="exerciseCoding"
  exerciseUrl, isCodeEditorEnabled, coding: {exerciseUrl}
  name, viewContent = JSON-строка {description: HTML}
  estimation: {
    startDate, timer, maxScore, deadline,
    activity: {
      id, name, weight, maxExercisesCount,
      averageScoreThreshold, isLateDaysEnabled, bestScoresCount
    }
  }
  reviewers, assignees, isTrackingStudents, attachments
  backloggedAt, taskId, id, order, state
```

`coding` не означает, что внутри обязательно есть редактор кода: у исследованной работы он выключен, условие ссылается на Drive, решение — файл `.ipynb`.

### Персональная работа

```text
{
  id, type, state,
  score, scoreSkillLevel, isSkillLevelEnabled,
  isLateDaysEnabled, extraScore,
  createdAt, startedAt, submitAt, rejectAt, evaluateAt,
  deadline, lateDays,
  exercise: {
    id, name, type, maxScore, startDate, deadline, timer,
    activity, viewContent, exerciseUrl, isCodeEditorEnabled,
    attachments, settings,
    questionOrders, areQuestionsShuffled, quizId, mode
  },
  course: {id, name, isArchived},
  theme: {id, name}, longread: {id, name},
  student: { ..., lateDaysBalance }, reviewer,
  solution: {type, solutionUrl, answers, attachments},
  scores, quizSessionId, evaluatedAttemptId, currentAttemptId, lastAttemptId
}
```

Поля `student` и `reviewer` содержат персональные данные; их полные значения намеренно не сохранены в репозитории. Будущим инструментам чтения заданий обычно не нужны контакты и внутренние идентификаторы всех участников.

Общий список `/tasks/student` возвращал массив, а не обёртку `items`. Пример элемента содержит идентификаторы работы/упражнения/курса/темы/лонгрида, состояние, даты, оценку, `lateDays`, LD-флаги и проверяющего. Полная детальная `solution` в проверенном примере элемента списка отсутствовала.

### Прогресс и ведомость

```text
/student/progress:
  {earnedScore, leftToEarnScore, maxScore}

/activities:
  [{id, name, exercisesCount, weight, maxExercisesCount,
    averageScoreThreshold, isLateDaysEnabled, bestScoresCount}]

/activities-performance:
  {
    items: [{activity: {..., isBlocker}, total, average, blockerTriggered}],
    normalizationScore, blockerEnabled, blockerScore,
    courseBlockerTriggered, activitiesBlockerTriggered, totalScore, totalWeight
  }

/student-performance:
  {
    tasks: [{id, state, score, normalizedScore, scoreSkillLevel,
      extraScore, normalizedExtraScore, exerciseId, maxScore, activity}],
    blockers: [{activityId, activityName, averageScoreThreshold}],
    total, blockerEnabled, courseBlockerTriggered,
    activitiesBlockerTriggered, blockerScore
  }
```

## Дополнительные наблюдавшиеся маршруты

| Путь | Наблюдение |
|---|---|
| `/api/micro-lms/calendar-events/recording-hosts` | 200, фильтр преподавателей видеозаписей |
| `/api/micro-lms/calendar-events/recording-events?offset=0&limit=20&myEvents=true&eventTypes=seminar&eventTypes=lecture&courseId=1127` | 200, таблица событий с потенциальными записями |
| `/api/micro-lms/calendar-events/slot-management/config` | 200, конфигурация выбора слотов; схема не изучена |
| `/api/micro-lms/course-selection/student/campaigns` | 200, кампании выбора курсов; схема не изучена |
| `/api/micro-lms/students/me` | 200, профиль LMS; полное тело отдельно не сохранялось |
| `/api/student-hub/students/me` | 200, профиль общего портала; схема не исследована |
| `/api/notification-hub/notifications/in-app/stats` | 200, статистика уведомлений |
| `/api/micro-lms/banners` | 200, баннеры |
| `/api/admin/configurations/lms-block-requests` | 204, конфигурация интерфейса; наличие пути не означает административных прав |

Сетевые URL телеметрии не включены: они не нужны для пользовательских функций MCP.

## Авторизация: что известно и что нет

- Начальный вход перенаправлял с `my.centraluniversity.ru` на `id.centraluniversity.ru/realms/central-university/login-actions/authenticate`.
- В URL входа наблюдались `client_id=api-gateway`, тип ответа `code` в параметрах обратного вызова и callback `/api/account/signin/callback`.
- Это согласуется с серверным потоком OIDC и realm-маршрутами Keycloak, но конкретная реализация и способ передачи сессии в API отдельно не проверялись.
- Пользователь ввёл пароль самостоятельно. Cookies, заголовки авторизации и refresh-токены не экспортировались и в файлы не записывались.
- Успех API внутри авторизованного браузера не доказывает, что автономный HTTP-клиент сможет воспроизвести вход или чтение. Это следующий отдельный технический этап.
- Нет проверки срока сессии, фонового обновления, CSRF, поведения после выхода и входа на внешние сервисы.

## Как продолжать сбор доказательств

При дальнейшей проверке наблюдать запросы при конкретных UI-действиях. Фиксировать HTTP-метод, путь, безопасные параметры, статус, форму ответа и пример связи ID. Не сохранять session-параметры, cookies, токены, полные подписанные ссылки и не открывать непроверенные URL по догадке. Записывающие операции проверять отдельно от чтения и только в согласованном объёме.

## Дополнение после восстановления доступа

| Путь | Подтверждение |
|---|---|
| `/api/micro-lms/courses/student?offset=0&limit=20&state=archived` | 200; UI 1–20 из 27 |
| `/api/micro-lms/courses/student?offset=20&limit=20&state=archived` | 200; UI 21–27 из 27 |
| `/api/micro-lms/tasks/student?state=evaluated&state=failed` | 200; архив завершённых работ |
| `/api/micro-lms/tasks/student?state=evaluated&state=failed&sortProperty=deadline&sortDirection=-1` | 200; тело изучено: массив 698 работ, состояния `evaluated`/`failed` |
| `/api/micro-lms/tasks/2289310/events` | 200; UI истории изучен; JSON-схема не разобрана |

Элемент архива работ имеет ключи `id`, `state`, `score`, `scoreSkillLevel`, `isLateDaysEnabled`, `extraScore`, `createdAt`, `startedAt`, `submitAt`, `rejectAt`, `evaluateAt`, `deadline`, `lateDays`, `exercise`, `course`, `theme`, `longread`, `reviewer`, `quizSessionId`. Архив работы не означает архив курса.

### Note: отдельный origin `https://note.cu.ru`

Ниже — только запросы, наблюдавшиеся при перезагрузке уже открытого силлабуса английского. Методы и тела запросов QL не зафиксированы; нельзя угадывать их по имени маршрута.

| Путь | Статус | Исследование |
|---|---:|---|
| `/api/v1/auth/user/refresh` | 401 | Значения учётных данных не читались |
| `/api/v1/account-settings?slug=default` | 200 | Маршрут наблюдался |
| `/api/v1/wiki/articles/4ad57fe1-5483-4b1d-8676-08e035d97f7e?viewMode=edit&latestVersionAt=1793172877` | 200 | Ключи метаданных изучены; `editorContentObject` не дал содержимого |
| `/api/v1/wiki/ql/article` | 200 | Метаданные статьи: название, публикация, обновление, хлебные крошки, свойства, права и др. |
| `/api/v1/wiki/ql/article_content` | 200 | `{data: [], paginate: ...}` в данном ответе; не подтверждает способ чтения полного текста |
| `/api/v1/wiki/ql/tree_to_article` | 200 | Маршрут наблюдался |

Ответ метаданных содержит поле `accessToken`; его значение намеренно не выводилось и не сохранялось. Наличие этого поля и `viewMode=edit` не означает права редактировать документ. Изменений и публикаций не было. Тексты двух силлабусов подтверждены через DOM браузера; работоспособность отдельного Note-клиента не подтверждена.

### Квизы: чтение завершённой попытки

Все ниже — реальные ответы 200 при открытии оценённого квиза 820/26139; HTTP-методы отдельно не фиксировались.

| Путь | Подтверждённая схема |
|---|---|
| `/api/micro-lms/tasks/1646399` | Обычная карточка работы; `type=questions`, `exercise.quizId=55129`, `timer=00:06:00`, `mode=byDeadline`, `settings.attemptsLimit=1`, `settings.evaluationStrategy=last` |
| `/api/micro-lms/quizzes/55129/questions` | Массив 10 элементов: `type`, `settings`, `options`, `id`, `content`, `score`, `order`, `attachments` |
| `/api/micro-lms/quizzes/attempts/57703` | `id`, `number`, `state`, `startedAt`, `finishedAt`, `questions`, `answers`, `results` |
| `/api/micro-lms/quizzes/sessions/1469000/attempts` | Массив одной попытки: `id`, `number`, `state`, `startedAt`, `finishedAt`, `score` |
| `/api/micro-lms/tasks/1646399/events` | Маршрут истории, UI прочитан |

Не путать `quizId`, `quizSessionId` и идентификатор попытки. Просмотр оценённой попытки не доказывает доступность вопросов будущего теста; запуск попытки — отдельное изменение состояния и может запустить таймер.
