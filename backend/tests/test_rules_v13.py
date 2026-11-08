from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.core.config import settings
from app.rules.engine import locate
from app.rules.loader import load_rules
from app.rules.matchers.base import MatchContext
from app.rules.matchers.image_matcher import match_image
from app.services.social_insurance_detector import detect_social_insurance
from app.services.stamp_detector import detect_blue_stamps

RULES = Path(__file__).resolve().parents[2] / "rules" / "rules.yaml"
VALID_ID = "11010519491231002X"


def _text_pdf(tmp_path, name: str, text: str) -> Path:
    path = tmp_path / name
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(pymupdf.Rect(40, 40, 555, 800), text, fontsize=10, fontname="china-s")
    doc.save(path)
    doc.close()
    return path


def _locate(path: Path, page_types: list[str] | None = None, blocks=None):
    doc = pymupdf.open(path)
    ruleset = load_rules(RULES)
    try:
        return locate(
            doc,
            ruleset,
            blocks_by_page=blocks or {},
            page_types=page_types or ["text"] * len(doc),
        )
    finally:
        doc.close()


def test_bid_letter_amounts_are_skipped(tmp_path):
    text = (
        "一、投标函及投标函附录\n"
        "我方愿意以人民币（大写）贰仟肆佰陆拾陆万零捌拾元整"
        "（¥24660080.00）的投标总报价完成本项目。\n"
        "投标总价：24660080.00 元。\n"
        "本页还包含法定代表人、联系人和地址等普通说明文字，用于补足文本长度。"
    )
    result = _locate(_text_pdf(tmp_path, "bid.pdf", text))
    assert not [b for b in result.boxes if b.rule_id in {"RED-10", "RED-21", "RED-23"}]


def test_amount_rules_still_fire_without_bid_letter(tmp_path):
    text = (
        "四、勘察设计费报价表\n"
        "设计费投标报价：1927.02 万元。\n"
        "合同金额为人民币贰佰万元整（¥2000000.00）。\n"
        "本段为普通说明文字，用于保证页面被识别为文本页并触发金额规则。"
    )
    result = _locate(_text_pdf(tmp_path, "amount.pdf", text))
    ids = {b.rule_id for b in result.boxes}
    assert "RED-10" in ids
    assert "RED-23" in ids


def test_person_certificate_number_rule(tmp_path):
    text = (
        "人员证书信息\n"
        "证书编号：AD244400388\n"
        "毕业证书编号：105361201202000170\n"
        "执业印章号：B11234400025510\n"
        "本页用于验证人员证书编号和执业印章号的严格遮挡。"
    )
    result = _locate(_text_pdf(tmp_path, "cert.pdf", text))
    values = {b.rule_id for b in result.boxes}
    assert "RED-25" in values
    assert len([b for b in result.boxes if b.rule_id == "RED-25"]) >= 2


def test_certificate_number_table_label_value(tmp_path):
    page = pymupdf.open()
    page.new_page(width=595, height=842)
    path = tmp_path / "table.pdf"
    page.save(path)
    page.close()

    html = (
        "<table><tr><td>姓名</td><td>张三</td></tr>"
        "<tr><td>证书编号</td><td>AD244400388</td></tr></table>"
    )
    blocks = {
        0: [
            {
                "type": "table",
                "text": "",
                "bbox": [100, 100, 900, 300],
                "page_idx": 0,
                "table_body": html,
            }
        ]
    }
    result = _locate(path, ["scan"], blocks)
    assert any(b.rule_id in {"RED-26", "RED-29"} for b in result.boxes)


def test_id_card_back_fields_redacted(tmp_path):
    path = tmp_path / "back.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    card = pymupdf.Rect(100, 100, 340, 252)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 25), 0)
    pix.set_rect(pix.irect, (220, 220, 220))
    page.insert_image(card, pixmap=pix)
    page.insert_text((card.x0 + 10, card.y0 + 120), "签发机关 广州市公安局", fontsize=8, fontname="china-s")
    page.insert_text((card.x0 + 10, card.y0 + 135), "有效期限 2020.01.01-2040.01.01", fontsize=8, fontname="china-s")
    doc.save(path)
    doc.close()

    doc = pymupdf.open(path)
    ruleset = load_rules(RULES)
    rule = ruleset.rule("RED-02")
    ctx = MatchContext(
        doc=doc,
        page_no=0,
        page=doc[0],
        page_type="scan",
        ruleset=ruleset,
        faces=[],
        face_detection=True,
    )
    try:
        boxes = match_image(rule, ctx)
    finally:
        doc.close()
    back = [b for b in boxes if b.note in {"id_card_back", "id_card_back_inferred"}]
    assert back
    assert back[0].rect.y0 > card.y0 + card.height * 0.5


def test_certificate_photo_is_not_treated_as_id_card(tmp_path):
    path = tmp_path / "cert_photo.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    card = pymupdf.Rect(100, 100, 340, 252)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 25), 0)
    pix.set_rect(pix.irect, (220, 220, 220))
    page.insert_image(card, pixmap=pix)
    page.insert_text((card.x0 + 10, card.y0 + 80), "毕业证书", fontsize=12, fontname="china-s")
    doc.save(path)
    doc.close()

    doc = pymupdf.open(path)
    ruleset = load_rules(RULES)
    rule = ruleset.rule("RED-02")
    ctx = MatchContext(
        doc=doc,
        page_no=0,
        page=doc[0],
        page_type="scan",
        ruleset=ruleset,
        faces=[pymupdf.Rect(card.x0 + 140, card.y0 + 60, card.x0 + 190, card.y0 + 120)],
        face_detection=True,
    )
    try:
        boxes = match_image(rule, ctx)
    finally:
        doc.close()
    assert boxes == []


def test_blue_stamp_detected_on_budget_page(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "blue_stamp_enabled", True)
    path = tmp_path / "budget.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((100, 100), "工程预算审核书", fontsize=16, fontname="china-s")
    page.draw_circle(pymupdf.Point(250, 400), 40, color=None, fill=(0.2, 0.4, 0.9))
    doc.save(path)
    doc.close()

    boxes, state = detect_blue_stamps(path, "test-budget")
    assert state == "official"
    assert boxes
    assert all(b.rule_id == "BLUE-STAMP" for b in boxes)


def test_social_insurance_barcode_and_code(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "social_insurance_enabled", True)
    path = tmp_path / "social.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((80, 100), "广东省直社会保险参保证明", fontsize=14, fontname="china-s")
    page.insert_text((80, 130), "参保人姓名：张三", fontsize=10, fontname="china-s")
    page.insert_text((380, 80), "验证码：202602029003565844", fontsize=8, fontname="china-s")
    doc.save(path)
    doc.close()

    blocks = {
        0: [
            {
                "type": "image",
                "text": "",
                "bbox": [650, 95, 800, 125],
                "page_idx": 0,
                "table_body": None,
            }
        ]
    }
    boxes, state = detect_social_insurance(path, "test-social", blocks)
    assert state == "official"
    notes = {b.note for b in boxes}
    assert "barcode" in notes
    assert "verify_code" in notes
    assert all(b.rule_id == "SS-CODE" for b in boxes)