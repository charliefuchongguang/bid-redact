from __future__ import annotations

import json
import zipfile

import pymupdf

from app.services.mineru_parse import (
    extract_layout_blocks,
    normalize_bbox_spaces,
    parse_result_zip,
)
from app.services.pdf_split import split_pdf

PAGE = (595.0, 842.0)


def test_point_bbox_is_normalized_to_canvas():
    blocks = [
        {"type": "text", "text": "a", "bbox": [100, 100, 500, 200], "page_idx": 0},
        {"type": "text", "text": "b", "bbox": [100, 700, 500, 820], "page_idx": 0},
    ]
    out, space = normalize_bbox_spaces(blocks, [PAGE])
    assert space == "point"
    assert out[0]["bbox"][2] > 800
    assert out[1]["bbox"][3] > 900


def test_normalized_bbox_is_kept():
    blocks = [
        {"type": "text", "text": "a", "bbox": [100, 100, 900, 900], "page_idx": 0},
    ]
    out, space = normalize_bbox_spaces(blocks, [PAGE])
    assert space == "normalized"
    assert out[0]["bbox"] == [100, 100, 900, 900]


def test_layout_middle_json_parsed():
    data = {
        "pdf_info": [
            {
                "page_idx": 0,
                "preproc_blocks": [
                    {
                        "type": "text",
                        "bbox": [10, 20, 300, 40],
                        "lines": [{"spans": [{"content": "hello "}, {"content": "world"}]}],
                    },
                    {"type": "figure", "bbox": [10, 50, 200, 150]},
                ],
            }
        ]
    }
    blocks = extract_layout_blocks(data)
    assert len(blocks) == 2
    assert blocks[0]["text"] == "hello world"
    assert blocks[0]["type"] == "text"
    assert blocks[1]["type"] == "image"


def test_zip_content_list_with_page_offset(tmp_path):
    payload = [
        {"type": "text", "text": "phone 13800138000", "bbox": [100, 100, 500, 200], "page_idx": 0}
    ]
    zip_path = tmp_path / "result.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("result/foo_content_list.json", json.dumps(payload, ensure_ascii=False))
        zf.writestr("result/images/a.jpg", b"not-an-image")

    blocks = parse_result_zip(zip_path, page_offset=3)
    assert len(blocks) == 1
    assert blocks[0]["page_idx"] == 3
    assert blocks[0]["text"].endswith("13800138000")


def test_split_pdf_pages_and_offsets(tmp_path):
    source = tmp_path / "five.pdf"
    doc = pymupdf.open()
    for i in range(5):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f"page {i + 1}", fontsize=14)
    doc.save(source)
    doc.close()

    parts = split_pdf(source, tmp_path / "parts", data_prefix="abc", max_pages=2, max_mb=200)
    assert [p.page_count for p in parts] == [2, 2, 1]
    assert [p.page_offset for p in parts] == [0, 2, 4]
    assert [p.page_range for p in parts] == ["1-2", "1-2", "1-1"]
    assert len({p.data_id for p in parts}) == 3
    for part in parts:
        part_doc = pymupdf.open(part.path)
        assert len(part_doc) == part.page_count
        part_doc.close()