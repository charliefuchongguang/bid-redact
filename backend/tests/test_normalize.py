from __future__ import annotations

import pymupdf

from app.rules.normalize import (
    extract_value_after,
    mineru_bbox_to_rect,
    normalize_ocr_text,
    text_span_bbox,
    text_span_bbox_uniform,
)


def test_mineru_bbox_normalized_to_page():
    page = pymupdf.Rect(0, 0, 595, 842)
    rect = mineru_bbox_to_rect(page, [0, 0, 1000, 1000])
    assert rect == page
    half = mineru_bbox_to_rect(page, [0, 0, 500, 500])
    assert half.x1 == 297.5
    assert half.y1 == 421.0


def test_normalize_ocr_text_fullwidth_and_spaces():
    text = "投标总价：￥1，292，072.30"
    norm, index = normalize_ocr_text(text)
    assert norm == "投标总价:¥1,292,072.30"
    assert len(index) == len(norm)
    assert text[index[0]] == "投"


def test_normalize_ocr_text_spaced_email():
    text = "电子邮箱：l i s i @e x a mp l e . c o m"
    norm, _ = normalize_ocr_text(text)
    assert "lisi@example.com" in norm


def test_extract_value_after_strips_colon():
    value = extract_value_after("手机：13800138000", 2, r"(?<!\d)1[3-9]\d{9}(?!\d)", 40)
    assert value is not None
    assert value[0] == "13800138000"


def test_span_bbox_uniform_and_weighted():
    bbox = [0, 0, 100, 10]
    uniform = text_span_bbox_uniform(bbox, "abcdefghij", 0, 5)
    assert uniform == [0, 0, 50, 10]
    weighted = text_span_bbox(bbox, "中文abcd", 0, 2)
    assert weighted[0] == 0 and weighted[2] == 50