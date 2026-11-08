from __future__ import annotations

import io
import json
import zipfile

import httpx
import pymupdf

from app.services.mineru_client import OfficialMineruClient, _api_error
from app.services.mineru_parse import parse_result_zip
from app.services.pdf_split import PdfPart


def _zip_bytes() -> bytes:
    payload = [
        {"type": "text", "text": "PHONE 13800138000", "bbox": [100, 100, 500, 200], "page_idx": 0}
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("foo_content_list.json", json.dumps(payload, ensure_ascii=False))
        zf.writestr("images/foo.jpg", b"x")
    return buffer.getvalue()


def test_official_client_submit_wait_download(tmp_path):
    zip_data = _zip_bytes()
    calls: list[tuple[str, str]] = []
    upload_content_types: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/file-urls/batch"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "batch_id": "batch-1",
                        "file_urls": ["https://upload.example/1"],
                    },
                },
            )
        if request.method == "PUT" and request.url.host == "upload.example":
            upload_content_types.append(request.headers.get("content-type"))
            return httpx.Response(200)
        if request.url.path.endswith("/extract-results/batch/batch-1"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "extract_result": [
                            {
                                "data_id": "p-1",
                                "state": "done",
                                "full_zip_url": "https://download.example/1.zip",
                            }
                        ]
                    },
                },
            )
        if request.url.host == "download.example":
            return httpx.Response(200, content=zip_data)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    pdf = tmp_path / "one.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "hello")
    doc.save(pdf)
    doc.close()
    part = PdfPart(path=pdf, page_offset=0, page_count=1, page_range="1-1", data_id="p-1")

    with OfficialMineruClient(token="test-token", transport=transport, poll_interval=0) as client:
        batch_id = client.submit([part])
        assert batch_id == "batch-1"
        results = client.wait(batch_id, 1)
        assert results[0]["state"] == "done"
        zip_path = client.download_zip("https://download.example/1.zip", tmp_path / "out.zip")

    blocks = parse_result_zip(zip_path)
    assert len(blocks) == 1
    assert blocks[0]["text"].endswith("13800138000")
    assert ("POST", "/api/v4/file-urls/batch") in calls
    assert upload_content_types == [None]


def test_error_messages_mapped():
    assert "Token 无效" in str(_api_error("A0202", ""))
    assert "每日" in str(_api_error("-60018", ""))
    assert _api_error("-60009", "").retryable