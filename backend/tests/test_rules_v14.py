from __future__ import annotations

from pathlib import Path

import pymupdf

from app.rules.engine import locate
from app.rules.loader import load_rules
from app.rules.matchers.base import MatchContext
from app.rules.matchers.image_matcher import match_image

RULES = Path(__file__).resolve().parents[2] / "rules" / "rules.yaml"


def _blank_pdf(tmp_path, name: str = "blank.pdf") -> Path:
    path = tmp_path / name
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    doc.save(path)
    doc.close()
    return path


def _locate(path: Path, page_types: list[str], blocks):
    doc = pymupdf.open(path)
    ruleset = load_rules(RULES)
    try:
        return locate(doc, ruleset, blocks_by_page=blocks, page_types=page_types)
    finally:
        doc.close()


def _table_block(html: str, bbox=None) -> dict:
    return {
        "type": "table",
        "text": "",
        "bbox": bbox or [100, 100, 900, 300],
        "page_idx": 0,
        "table_body": html,
    }


def test_table_phone_scan_all_cells(tmp_path):
    html = (
        "<table>"
        "<tr><td>单位名称</td><td>联系人及电话</td></tr>"
        "<tr><td>某建设单位</td><td>洪楚鉴 13502382992</td></tr>"
        "</table>"
    )
    result = _locate(_blank_pdf(tmp_path), ["scan"], {0: [_table_block(html)]})
    phones = [b for b in result.boxes if b.rule_id == "RED-27"]
    assert len(phones) == 1
    assert "13502382992" in phones[0].value


def test_table_certificate_column_scan_all_cells(tmp_path):
    html = (
        "<table>"
        "<tr><td>证书名称</td><td>级别</td><td>证号</td></tr>"
        "<tr><td>注册土木工程师</td><td>正高</td><td>2500101341699</td></tr>"
        "</table>"
    )
    result = _locate(_blank_pdf(tmp_path), ["scan"], {0: [_table_block(html)]})
    certs = [b for b in result.boxes if b.rule_id == "RED-29"]
    assert len(certs) == 1
    assert certs[0].value == "2500101341699"


def test_stacked_id_front_and_back_split(tmp_path):
    path = tmp_path / "stacked.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    card = pymupdf.Rect(100, 100, 340, 400)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 50), 0)
    pix.set_rect(pix.irect, (220, 220, 220))
    page.insert_image(card, pixmap=pix)
    page.insert_text((120, 170), "姓名 张三  公民身份号码", fontsize=9, fontname="china-s")
    page.insert_text((120, 330), "签发机关 广州市公安局", fontsize=9, fontname="china-s")
    page.insert_text((120, 350), "有效期限 2020.01.01-2040.01.01", fontsize=9, fontname="china-s")
    doc.save(path)
    doc.close()

    doc = pymupdf.open(path)
    ruleset = load_rules(RULES)
    ctx = MatchContext(
        doc=doc,
        page_no=0,
        page=doc[0],
        page_type="scan",
        ruleset=ruleset,
        faces=[pymupdf.Rect(250, 130, 300, 200)],
        face_detection=True,
    )
    try:
        boxes = match_image(ruleset.rule("RED-02"), ctx)
    finally:
        doc.close()

    notes = {b.note for b in boxes}
    assert "id_card_number_bottom" in notes
    assert any("id_card_back" in note for note in notes)


def test_certificate_number_fallback_when_ocr_missing(tmp_path):
    path = tmp_path / "cert.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    card = pymupdf.Rect(100, 100, 400, 300)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 25), 0)
    pix.set_rect(pix.irect, (220, 220, 220))
    page.insert_image(card, pixmap=pix)
    page.insert_text((140, 170), "毕业证书", fontsize=12, fontname="china-s")
    doc.save(path)
    doc.close()

    doc = pymupdf.open(path)
    ruleset = load_rules(RULES)
    ctx = MatchContext(
        doc=doc,
        page_no=0,
        page=doc[0],
        page_type="scan",
        ruleset=ruleset,
        faces=[pymupdf.Rect(310, 140, 360, 200)],
        face_detection=True,
    )
    try:
        boxes = match_image(ruleset.rule("RED-02"), ctx)
    finally:
        doc.close()
    assert any(
        b.rule_id == "RED-25" and "cert_number_fallback" in b.note for b in boxes
    )