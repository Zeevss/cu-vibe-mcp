import json
from io import BytesIO

import httpx
import pytest
from pypdf import PdfWriter

from lms_mcp.config import Config, LMSError
from lms_mcp.content import FILE_HOST, ContentService, extract, note_url
from lms_mcp.service import LMSService


class MaterialService:
    def __init__(self, client):
        self.client = client

    async def get_longread(self, _):
        return {
            "data": {
                "blocks": [
                    {
                        "id": 2,
                        "discriminator": "file",
                        "content": {"filename": "longreads/1/lesson.ipynb", "version": "v1"},
                    }
                ]
            }
        }


async def test_export_notebook_without_sending_portal_cookie(make_client, tmp_path):
    notebook = json.dumps(
        {
            "cells": [
                {"cell_type": "markdown", "source": ["# Lesson"]},
                {"cell_type": "code", "source": ["print(1)"]},
            ]
        }
    ).encode()

    def api(request):
        assert request.url.path == "/api/micro-lms/content/download-link"
        assert request.url.params["version"] == "v1"
        return httpx.Response(200, json={"url": f"https://{FILE_HOST}/lesson?X-Amz-Signature=temporary"})

    def download(request):
        assert "cookie" not in request.headers
        assert "authorization" not in request.headers
        return httpx.Response(200, content=notebook)

    content = ContentService(
        MaterialService(make_client(api)), Config(tmp_path), download_transport=httpx.MockTransport(download)
    )
    result = (await content.export_material(1, 2))["data"]
    assert result["extraction"] == "notebook_sources"
    assert "# Lesson" in result["text"] and "```python" in result["text"]
    assert __import__("pathlib").Path(result["path"]).read_bytes() == notebook
    assert "Signature" not in json.dumps(result)


async def test_download_rejects_external_url_before_network(make_client, tmp_path):
    client = make_client(lambda r: httpx.Response(200, json={"url": "https://evil.example/steal"}))

    def unexpected(_):
        pytest.fail("Must not fetch untrusted host")

    content = ContentService(
        MaterialService(client), Config(tmp_path), download_transport=httpx.MockTransport(unexpected)
    )
    with pytest.raises(LMSError, match="хранилище"):
        await content.export_material(1, 2)


async def test_download_has_size_bound(make_client, tmp_path):
    client = make_client(lambda r: httpx.Response(200, json={"url": f"https://{FILE_HOST}/large"}))
    content = ContentService(
        MaterialService(client),
        Config(tmp_path, max_download_bytes=4),
        download_transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"12345")),
    )
    with pytest.raises(LMSError, match="лимит"):
        await content.export_material(1, 2)
    assert not list(tmp_path.glob("downloads/*"))


def test_pdf_and_corrupt_material_are_explicit():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)
    assert extract(stream.getvalue(), "scan.pdf")["extraction"] == "no_text_layer"
    assert extract(b"not a PDF", "bad.pdf")["extraction"] == "failed"


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/at/anything",
        "https://note.cu.ru@evil.example/at/x",
        "http://note.cu.ru/at/x",
        "https://note.cu.ru:444/at/x",
    ],
)
def test_syllabus_origin_is_restricted(url):
    with pytest.raises(LMSError):
        note_url(url)


def test_note_link_canonicalization():
    article = "845f3aad-e6ef-40e2-985c-b0678e808987"
    space = "ef5cd6c2-3352-443d-9efd-29440d5ab735"
    assert (
        note_url(f"https://note.cu.ru/space/{space}/article/{article}") == f"https://note.cu.ru/at/{article}"
    )


async def test_note_tables_and_cookie_scope(make_client, monkeypatch, tmp_path, store):
    html = (
        "<h2>Система оценивания</h2><table><tr><td>ДЗ</td><td>20%</td></tr></table><p>"
        + "правила " * 30
        + "</p>"
    )

    class Editor:
        def get_attribute(self, _):
            return html

    class Driver:
        title = "Syllabus"
        closed = False
        current_url = "https://note.cu.ru/"
        added = []

        def get(self, url):
            assert "my.centraluniversity" not in url

        def add_cookie(self, c):
            self.added.append(c)

        def find_elements(self, *a):
            return [Editor()]

        def quit(self):
            self.closed = True

    store.put(
        __import__("lms_mcp.session", fromlist=["parse_cookies"]).parse_cookies("n=note-session", "note"),
        "note",
    )
    monkeypatch.setattr("lms_mcp.content.select_browser", lambda _: None)
    client = make_client(
        lambda r: httpx.Response(
            200,
            json={"settings": {"syllabusUrl": "https://note.cu.ru/at/845f3aad-e6ef-40e2-985c-b0678e808987"}},
        )
    )
    driver = Driver()
    content = ContentService(LMSService(client), Config(tmp_path), driver_factory=lambda *a, **k: driver)
    result = await content.get_syllabus(1127)
    assert "| ДЗ | 20% |" in result["data"]["markdown"]
    assert all(c["name"] != "session" for c in driver.added)
    assert driver.added[0]["value"] == "note-session"
    assert driver.closed
