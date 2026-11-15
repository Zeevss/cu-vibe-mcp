import json
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from markdownify import markdownify

from .client import LMSClient
from .config import PORTAL, LMSError

MSK = ZoneInfo("Europe/Moscow")
ACTIVE = ["inProgress", "backlog", "submitted", "review", "reworking"]
FINISHED = ["evaluated", "failed"]
LABELS = {
    "inProgress": "В работе",
    "backlog": "Задано",
    "submitted": "Решение прикреплено",
    "review": "На проверке",
    "reworking": "На доработке",
    "evaluated": "Оценено",
    "failed": "Не сдано",
}
SENSITIVE = {
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "authorization",
    "cookie",
    "cookies",
    "email",
    "phone",
    "phonenumber",
    "password",
    "reviewer",
    "reviewers",
    "assignees",
}


def clean(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key.lower().replace("_", "") in SENSITIVE:
                continue
            if key == "student":
                if isinstance(item, dict) and "lateDaysBalance" in item:
                    result[key] = {"lateDaysBalance": item["lateDaysBalance"]}
                continue
            result[key] = clean(item)
        return result
    if isinstance(value, list):
        return [clean(x) for x in value]
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        u = urlsplit(value)
        if any(p in u.query.lower() for p in ("x-amz-", "token=", "signature=", "credential=")):
            return urlunsplit((u.scheme, u.netloc, u.path, "", ""))
    return value


def positive(value: int):
    if value < 1:
        raise LMSError("ID должен быть положительным")
    return value


def envelope(data, source, **extra):
    return dict(data=clean(data), source_url=source, fetched_at=datetime.now(UTC).isoformat(), **extra)


def parse_date(value: str):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=MSK) if dt.tzinfo is None else dt
    except (ValueError, TypeError):
        raise LMSError("Неверная дата; используйте ISO 8601, например 2026-11-15T22:00:00+03:00") from None


def moscow(value):
    return parse_date(value).astimezone(MSK).isoformat() if value else None


def task_summary(task):
    exercise = task.get("exercise") or {}
    course = task.get("course") or {}
    theme = task.get("theme") or {}
    longread = task.get("longread") or {}
    link = None
    if all(x.get("id") for x in (course, theme, longread)):
        archive = "archived" if course.get("isArchived") else "actual"
        link = (
            f"{PORTAL}/learn/courses/view/{archive}/{course['id']}/themes/"
            f"{theme['id']}/longreads/{longread['id']}"
        )
    return dict(
        id=task["id"],
        name=exercise.get("name"),
        type=exercise.get("type"),
        state=task.get("state"),
        status_label=LABELS.get(task.get("state"), task.get("state")),
        score=task.get("score"),
        max_score=exercise.get("maxScore"),
        extra_score=task.get("extraScore"),
        deadline=task.get("deadline"),
        deadline_moscow=moscow(task.get("deadline")),
        original_deadline=exercise.get("deadline"),
        original_deadline_moscow=moscow(exercise.get("deadline")),
        late_days=task.get("lateDays"),
        late_days_enabled=task.get("isLateDaysEnabled"),
        activity_late_days_enabled=(exercise.get("activity") or {}).get("isLateDaysEnabled"),
        can_extend_now=None,
        course=course,
        theme=theme,
        longread=longread,
        source_url=link,
    )


def material_text(block):
    view = block.get("viewContent")
    if isinstance(view, str):
        try:
            view = json.loads(view)
        except ValueError:
            view = {"value": view}
    if not isinstance(view, dict):
        return None
    html = view.get("value") or view.get("description")
    return markdownify(html, heading_style="ATX") if isinstance(html, str) else None


class LMSService:
    def __init__(self, client: LMSClient):
        self.client = client

    async def list_courses(self, archived=False, offset=0, limit=100, query=None):
        if offset < 0 or not 1 <= limit <= 500:
            raise LMSError("offset ≥ 0; limit от 1 до 500")
        # Drain source pagination before applying optional local search.
        items, api_offset, total = [], 0, None
        while total is None or api_offset < total:
            page = await self.client.get(
                "/api/micro-lms/courses/student",
                {"offset": api_offset, "limit": 100, "state": "archived" if archived else "published"},
            )
            if not isinstance(page, dict) or not isinstance(page.get("items"), list):
                raise LMSError("Изменилась схема каталога курсов")
            batch = page["items"]
            total = page.get("paging", {}).get("totalCount")
            items.extend(batch)
            api_offset += len(batch)
            if not batch or (total is None and len(batch) < 100):
                break
            if api_offset >= 10000:
                raise LMSError("Не удалось завершить пагинацию каталога")
        if query:
            items = [x for x in items if query.casefold() in x.get("name", "").casefold()]
        return envelope(
            dict(
                items=items[offset : offset + limit],
                total_count=len(items),
                offset=offset,
                limit=limit,
                next_offset=offset + limit if offset + limit < len(items) else None,
            ),
            f"{PORTAL}/learn/courses/view/{'archived' if archived else 'actual'}",
        )

    async def get_course(self, course_id):
        course_id = positive(course_id)
        data = await self.client.get(f"/api/micro-lms/courses/{course_id}/overview")
        progress = await self.client.get(f"/api/micro-lms/courses/{course_id}/student/progress")
        deadlines = await self.client.get("/api/micro-lms/deadlines", {"limit": 10, "courseId": course_id})
        archive = "archived" if data.get("isArchived") else "actual"
        return envelope(
            dict(course=data, progress=progress, deadlines=deadlines),
            f"{PORTAL}/learn/courses/view/{archive}/{course_id}",
        )

    async def get_gradebook(self, course_id=None, archived=False):
        if course_id is None:
            data = await self.client.get(
                "/api/micro-lms/performance/student", {"isArchived": str(archived).lower()}
            )
        else:
            base = f"/api/micro-lms/courses/{positive(course_id)}"
            data = {}
            for key, suffix in [
                ("activities", "activities"),
                ("activities_performance", "activities-performance"),
                ("student_performance", "student-performance"),
                ("progress", "student/progress"),
            ]:
                data[key] = await self.client.get(f"{base}/{suffix}")
        return envelope(
            data,
            f"{PORTAL}/learn/reports/student-performance",
            notes=[
                "Средние и итоги рассчитаны LMS. null — отсутствие оценки, а не ноль.",
                "Блокеры и требования силлабуса следует читать отдельно.",
            ],
        )

    async def list_assignments(
        self,
        course_id=None,
        states=None,
        course_archived=None,
        deadline_from=None,
        deadline_before=None,
        offset=0,
        limit=50,
    ):
        states = ACTIVE if states is None else states
        if not states or any(x not in ACTIVE + FINISHED for x in states):
            raise LMSError("Неизвестные или пустые состояния заданий")
        if offset < 0 or not 1 <= limit <= 200:
            raise LMSError("offset ≥ 0; limit от 1 до 200")
        if course_id is not None:
            positive(course_id)
        start = parse_date(deadline_from) if deadline_from else None
        end = parse_date(deadline_before) if deadline_before else None
        if start and end and start >= end:
            raise LMSError("deadline_from должен быть раньше deadline_before")
        tasks = await self.client.get("/api/micro-lms/tasks/student", [("state", s) for s in states])
        if not isinstance(tasks, list):
            raise LMSError("Изменилась схема списка заданий")
        selected = []
        for task in tasks:
            course = task.get("course") or {}
            if course_id is not None and course.get("id") != course_id:
                continue
            if course_archived is not None and course.get("isArchived") != course_archived:
                continue
            deadline = parse_date(task["deadline"]) if task.get("deadline") else None
            if (start or end) and deadline is None:
                continue
            if start and deadline < start or end and deadline >= end:
                continue
            selected.append(task_summary(task))
        selected.sort(
            key=lambda x: parse_date(x["deadline"]) if x["deadline"] else datetime.max.replace(tzinfo=UTC)
        )
        return envelope(
            dict(
                items=selected[offset : offset + limit],
                total_count=len(selected),
                offset=offset,
                limit=limit,
                next_offset=offset + limit if offset + limit < len(selected) else None,
            ),
            f"{PORTAL}/learn/tasks",
            notes=[
                "Интервал сроков [deadline_from, deadline_before).",
                "Используются личные дедлайны, включая LD.",
            ],
        )

    async def get_assignment(self, task_id, include_history=True):
        task_id = positive(task_id)
        task = await self.client.get(f"/api/micro-lms/tasks/{task_id}")
        summary = task_summary(task)
        result = dict(summary=summary, task=task, description=material_text(task.get("exercise") or {}))
        if include_history:
            result["history"] = await self.client.get(f"/api/micro-lms/tasks/{task_id}/events")
        return envelope(result, summary["source_url"])

    async def get_late_days(self, task_id=None):
        profile = await self.client.get("/api/micro-lms/students/me")
        if not isinstance(profile, dict) or "lateDaysBalance" not in profile:
            raise LMSError("Изменилась схема баланса LD")
        data = {"balance": profile["lateDaysBalance"]}
        if task_id is not None:
            task = await self.client.get(f"/api/micro-lms/tasks/{positive(task_id)}")
            summary = task_summary(task)
            data["assignment"] = {
                k: summary[k]
                for k in (
                    "id",
                    "state",
                    "deadline",
                    "deadline_moscow",
                    "original_deadline",
                    "late_days",
                    "late_days_enabled",
                    "activity_late_days_enabled",
                    "can_extend_now",
                )
            }
        return envelope(
            data,
            PORTAL + "/learn/tasks",
            notes=[
                "Признак разрешения LD не гарантирует возможность переноса прямо сейчас.",
                "Инструмент не расходует LD и не меняет дедлайн.",
            ],
        )

    async def get_longread(self, longread_id):
        longread_id = positive(longread_id)
        meta = await self.client.get(f"/api/micro-lms/longreads/{longread_id}")
        page = await self.client.get(f"/api/micro-lms/longreads/{longread_id}/materials", {"limit": 10000})
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            raise LMSError("Изменилась схема материалов")
        blocks = sorted(page["items"], key=lambda x: x.get("order") or 0)
        for block in blocks:
            block["markdown"] = material_text(block)
        paging = page.get("paging") or {}
        complete = paging.get("totalCount", len(blocks)) <= len(blocks)
        return envelope(
            dict(longread=meta, blocks=blocks),
            PORTAL + f"/api/micro-lms/longreads/{longread_id}",
            complete=complete,
        )

    async def get_quiz_result(self, task_id):
        task = await self.client.get(f"/api/micro-lms/tasks/{positive(task_id)}")
        if task.get("type") != "questions" or task.get("state") != "evaluated":
            raise LMSError("Разрешён просмотр только уже оценённого теста; новая попытка не запускается")
        quiz_id = task.get("exercise", {}).get("quizId")
        attempt_id = task.get("evaluatedAttemptId")
        session_id = task.get("quizSessionId")
        if not quiz_id or not attempt_id or not session_id:
            raise LMSError("Нет идентификаторов оценённой попытки")
        return envelope(
            dict(
                summary=task_summary(task),
                settings=task["exercise"].get("settings"),
                timer=task["exercise"].get("timer"),
                questions=await self.client.get(f"/api/micro-lms/quizzes/{positive(quiz_id)}/questions"),
                attempt=await self.client.get(f"/api/micro-lms/quizzes/attempts/{positive(attempt_id)}"),
                attempts=await self.client.get(
                    f"/api/micro-lms/quizzes/sessions/{positive(session_id)}/attempts"
                ),
            ),
            task_summary(task)["source_url"],
        )

    async def get_dashboard(
        self, course_id=None, deadline_from=None, deadline_before=None, include_gradebook=True, limit=100
    ):
        """One model call; normally four portal requests for an all-course overview."""
        import asyncio

        jobs = {
            "courses": self.list_courses(limit=500),
            "assignments": self.list_assignments(
                course_id=course_id,
                course_archived=False,
                deadline_from=deadline_from,
                deadline_before=deadline_before,
                limit=limit,
            ),
            "late_days": self.get_late_days(),
        }
        if include_gradebook:
            jobs["gradebook"] = self.get_gradebook(course_id)
        values = await asyncio.gather(*jobs.values(), return_exceptions=True)
        data, errors = {}, {}
        for name, value in zip(jobs, values, strict=True):
            if isinstance(value, Exception):
                errors[name] = str(value) if isinstance(value, LMSError) else "Ошибка раздела"
            else:
                data[name] = value
        if not data:
            from .config import AuthRequired

            if all(isinstance(value, AuthRequired) for value in values):
                raise AuthRequired("Нужен вход: cu-lms-mcp login или import-cookie")
            raise LMSError("Не удалось получить ни один раздел обзора")
        return envelope({"sections": data, "errors": errors}, PORTAL + "/learn/", complete=not errors)
