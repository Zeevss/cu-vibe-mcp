import httpx
import pytest

from lms_mcp.config import Config, LMSError
from lms_mcp.runner import LocalRunner


async def test_dashboard_and_batch_reuse_portal_reads(make_client, tmp_path):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith("/courses/student"):
            return httpx.Response(200, json={"items": [{"id": 1}], "paging": {"totalCount": 1}})
        if request.url.path.endswith("/students/me"):
            return httpx.Response(200, json={"lateDaysBalance": 24})
        return httpx.Response(200, json=[])

    client = make_client(handler)
    plan = {
        "calls": [
            {"method": "get_dashboard"},
            {"method": "get_late_days"},
            {"method": "get_gradebook"},
            {"method": "list_courses", "params": {"limit": 500}},
        ]
    }
    result = await LocalRunner(Config(tmp_path), client).run(plan)
    assert result["ok"], result
    assert len(seen) == 4
    assert result["metrics"] == {"api_requests": 4, "cache_hits": 3}
    assert result["results"][0]["result"]["data"]["sections"]["late_days"]["data"]["balance"] == 24
    # The next invocation must not reuse stale portal data.
    await LocalRunner(Config(tmp_path), client).run({"method": "get_late_days"})
    assert len(seen) == 5


@pytest.mark.parametrize(
    "bad",
    [
        {"method": "auth_login"},
        {"method": "batch"},
        {"method": "get_course", "params": {"course_id": "oops"}},
        {"method": "get_course", "params": {"course_id": 1, "typo": True}},
        {"method": "not_a_method"},
    ],
)
async def test_invalid_plan_executes_nothing(make_client, tmp_path, bad):
    def unexpected(_):
        pytest.fail("Invalid plan made an API request")

    runner = LocalRunner(Config(tmp_path), make_client(unexpected))
    with pytest.raises(LMSError):
        await runner.run({"calls": [{"method": "get_late_days"}, bad]})


async def test_dashboard_partial_error_is_explicit(make_client, tmp_path):
    def handler(request):
        if request.url.path.endswith("/students/me"):
            return httpx.Response(200, json={"lateDaysBalance": 24})
        return httpx.Response(500)

    result = await LocalRunner(Config(tmp_path), make_client(handler)).run({"method": "get_dashboard"})
    data = result["results"][0]["result"]
    assert data["complete"] is False
    assert set(data["data"]["errors"]) == {"courses", "assignments", "gradebook"}
    assert set(data["data"]["sections"]) == {"late_days"}


async def test_expired_session_fails_and_stop_on_error(make_client, store, tmp_path):
    store.clear()
    runner = LocalRunner(Config(tmp_path), make_client(lambda _: pytest.fail("No session")))
    result = await runner.run(
        {"calls": [{"method": "get_dashboard"}, {"method": "get_late_days"}], "stop_on_error": True}
    )
    assert not result["ok"] and len(result["results"]) == 1
    assert "login" in result["results"][0]["error"]
