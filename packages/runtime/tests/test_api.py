import json

import httpx
import pytest

from lms_mcp.config import AuthRequired, LMSError
from lms_mcp.service import LMSService, clean


@pytest.mark.parametrize(
    "status,content_type,body",
    [(302, "text/html", b""), (401, "text/plain", b""), (200, "text/html", b"<html>login</html>")],
)
async def test_expired_login_is_not_empty_list(make_client, status, content_type, body):
    client = make_client(
        lambda r: httpx.Response(status, headers={"content-type": content_type}, content=body)
    )
    with pytest.raises(AuthRequired):
        await client.get("/api/micro-lms/courses/student")


async def test_no_auth_never_requests_network(make_client, store):
    store.clear()

    def unexpected(_):
        pytest.fail("No request without a saved session")

    with pytest.raises(AuthRequired):
        await make_client(unexpected).get("/api/micro-lms/students/me")


async def test_cookie_rotation_and_no_redirect_follow(make_client, store):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200, json={"ok": True}, headers={"set-cookie": "session=rotated; Path=/; Secure; HttpOnly"}
        )

    await make_client(handler).get("/api/micro-lms/students/me")
    assert len(seen) == 1
    assert seen[0].headers["cookie"] == "session=test-secret"
    assert store.get()[0]["value"] == "rotated"


async def test_pagination_does_not_lose_27_courses(make_client):
    calls = []

    def handler(r):
        offset = int(r.url.params["offset"])
        calls.append(offset)
        return httpx.Response(
            200,
            json={
                "items": [{"id": i, "name": f"course {i}"} for i in range(offset, min(offset + 20, 27))],
                "paging": {"totalCount": 27},
            },
        )

    result = await LMSService(make_client(handler)).list_courses(archived=True)
    assert result["data"]["total_count"] == 27
    assert calls == [0, 20]
    assert len(result["data"]["items"]) == 27


def task(id, deadline, archived=False, score=None):
    return {
        "id": id,
        "state": "review",
        "score": score,
        "deadline": deadline,
        "lateDays": 2,
        "isLateDaysEnabled": True,
        "course": {"id": 1127, "isArchived": archived},
        "theme": {"id": 10010},
        "longread": {"id": 43826},
        "exercise": {
            "name": "HW",
            "type": "coding",
            "maxScore": 10,
            "deadline": "2026-11-08T19:00:00+00:00",
            "activity": {"isLateDaysEnabled": True},
        },
    }


async def test_deadline_filter_uses_personal_date_and_independent_archive(make_client):
    tasks = [
        task(1, "2026-11-10T19:00:00Z"),
        task(2, "2026-11-11T19:00:00Z", True),
        task(3, "2026-11-11T21:00:00Z"),
        task(4, None),
    ]

    def handler(r):
        assert r.url.params.get_list("state") == ["review"]
        return httpx.Response(200, json=tasks)

    result = await LMSService(make_client(handler)).list_assignments(
        states=["review"], course_archived=False, deadline_from="2026-11-10", deadline_before="2026-11-12"
    )
    (item,) = result["data"]["items"]
    assert item["id"] == 1
    assert item["score"] is None
    assert item["deadline_moscow"] == "2026-11-10T22:00:00+03:00"
    assert item["original_deadline"] != item["deadline"]
    assert item["can_extend_now"] is None


async def test_gradebook_preserves_server_blockers_and_nulls(make_client):
    routes = {
        "activities": [{"weight": 0.3, "maxExercisesCount": 2, "averageScoreThreshold": 3.5}],
        "activities-performance": {"totalScore": 2, "courseBlockerTriggered": True},
        "student-performance": {"tasks": [{"score": None}], "blockers": [{"activityId": 1}]},
        "progress": {"earnedScore": 2.04},
    }
    service = LMSService(make_client(lambda r: httpx.Response(200, json=routes[r.url.path.split("/")[-1]])))
    data = (await service.get_gradebook(1127))["data"]
    assert data["student_performance"]["tasks"][0]["score"] is None
    assert data["activities_performance"]["courseBlockerTriggered"] is True
    assert data["progress"]["earnedScore"] == 2.04


def test_output_strips_credentials_and_contact_data():
    raw = {
        "accessToken": "secret",
        "student": {"email": "private", "lateDaysBalance": 24},
        "reviewer": {"email": "private"},
        "url": "https://example.com/f.pdf?X-Amz-Signature=secret",
    }
    data = clean(raw)
    assert data == {"student": {"lateDaysBalance": 24}, "url": "https://example.com/f.pdf"}
    assert "secret" not in json.dumps(data)


async def test_quiz_does_not_start_attempt(make_client):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"type": "questions", "state": "inProgress"})

    with pytest.raises(LMSError):
        await LMSService(make_client(handler)).get_quiz_result(1)
    assert len(seen) == 1 and seen[0].method == "GET"


async def test_quiz_result_reads_only_evaluated_attempt(make_client):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        assert request.method == "GET"
        if "/tasks/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    **task(1, "2026-11-10T19:00:00Z"),
                    "type": "questions",
                    "state": "evaluated",
                    "evaluatedAttemptId": 57703,
                    "quizSessionId": 1469000,
                    "exercise": {"quizId": 55129, "settings": {"attemptsLimit": 1}},
                },
            )
        return httpx.Response(200, json=[])

    result = await LMSService(make_client(handler)).get_quiz_result(1)
    assert result["data"]["settings"]["attemptsLimit"] == 1
    assert seen == [
        "/api/micro-lms/tasks/1",
        "/api/micro-lms/quizzes/55129/questions",
        "/api/micro-lms/quizzes/attempts/57703",
        "/api/micro-lms/quizzes/sessions/1469000/attempts",
    ]
