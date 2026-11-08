from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
import pymupdf

from app import pipeline as pipeline_module
from app.core.config import settings
from app.rules.loader import load_rules
from app.services import mineru_usage
from app.services.mineru_client import OfficialMineruClient

RULES = Path(__file__).resolve().parents[2] / "rules" / "rules.yaml"


def _scanned_pdf(path: Path) -> None:
    source = pymupdf.open()
    page = source.new_page(width=595, height=842)
    page.insert_text((72, 200), "联系电话：13800138000", fontsize=14)
    rect = page.search_for("13800138000")[0]
    pix = page.get_pixmap(dpi=150)
    scan = source.new_page(width=595, height=842)
    scan.insert_image(scan.rect, pixmap=pix)
    source.save(path)
    source.close()
    return rect


def _zip_bytes(rect: pymupdf.Rect) -> bytes:
    payload = [
        {
            "type": "text",
            "text": "联系电话：13800138000",
            "bbox": [rect.x0, rect.y0, rect.x1, rect.y1],
            "page_idx": 0,
        }
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("result/scan_content_list.json", json.dumps(payload, ensure_ascii=False))
    return buffer.getvalue()


def test_pipeline_uses_official_mineru_and_cache(tmp_path, monkeypatch):
    text_rect = None
    source = tmp_path / "scan.pdf"
    # build a one-page scanned PDF (the first page is text, second is its raster image)
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 200), "联系电话：13800138000", fontsize=14)
    text_rect = page.search_for("13800138000")[0]
    pix = page.get_pixmap(dpi=150)
    scan = doc.new_page(width=595, height=842)
    scan.insert_image(scan.rect, pixmap=pix)
    doc.delete_page(0)
    doc.save(source)
    doc.close()

    zip_data = _zip_bytes(text_rect)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "POST" and request.url.path.endswith("/file-urls/batch"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"batch_id": "b1", "file_urls": ["https://upload.example/1"]},
                },
            )
        if request.method == "PUT" and request.url.host == "upload.example":
            return httpx.Response(200)
        if request.url.path.endswith("/extract-results/batch/b1"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "extract_result": [
                            {
                                "file_name": "scan.pdf",
                                "data_id": "x-1",
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
    monkeypatch.setattr(settings, "mineru_api_token", "test-token")
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(mineru_usage, "_FILE", tmp_path / "data" / "mineru" / "usage.json")
    monkeypatch.setattr(
        pipeline_module,
        "OfficialMineruClient",
        lambda: OfficialMineruClient(
            token="test-token", transport=transport, poll_interval=0
        ),
    )
    settings.ensure_dirs()

    ruleset = load_rules(RULES)
    out = tmp_path / "out.pdf"
    report = pipeline_module.run(
        source=source,
        output=out,
        ruleset=ruleset,
        mineru_mode="auto",
    )
    assert report["mineru"] == "official"
    assert report["box_count"] > 0
    assert report["mineru_bbox_space"] == "point"
    assert out.exists()
    assert any("POST" in call for call in calls)

    before = len(calls)
    report2 = pipeline_module.run(
        source=source,
        output=tmp_path / "out2.pdf",
        ruleset=ruleset,
        mineru_mode="auto",
    )
    assert report2["mineru"] == "cache"
    assert len(calls) == before