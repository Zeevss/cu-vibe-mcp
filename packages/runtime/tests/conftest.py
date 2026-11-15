import httpx
import pytest

from lms_mcp.client import LMSClient
from lms_mcp.session import SessionStore, parse_cookies


@pytest.fixture
def store(tmp_path):
    value = SessionStore(tmp_path / "data")
    value.put(parse_cookies("session=test-secret"))
    return value


@pytest.fixture
def make_client(store):
    def create(handler):
        return LMSClient(store, httpx.MockTransport(handler))

    return create
