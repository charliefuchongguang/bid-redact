from __future__ import annotations

from pathlib import Path

import pymupdf

from app.rules.loader import load_rules
from app.rules.matchers.base import MatchContext
from app.rules.matchers.image_matcher import match_image

RULES = Path(__file__).resolve().parents[2] / "rules" / "rules.yaml"
ID = "11010519491231002X"


def _card_pdf(tmp_path, rect: pymupdf.Rect, number: str | None):
    path = tmp_path / "card.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    height = max(1, round(40 * rect.height / rect.width))
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, height), 0)
    pix.set_rect(pix.irect, (220, 220, 220))
    page.insert_image(rect, pixmap=pix)
    if number:
        page.insert_text((rect.x0 + 10, rect.y1 - 8), number, fontsize=8)
    doc.save(path)
    doc.close()
    return path


def _context(path: Path):
    doc = pymupdf.open(path)
    ruleset = load_rules(RULES)
    rule = ruleset.rule("RED-02")
    ctx = MatchContext(
        doc=doc,
        page_no=0,
        page=doc[0],
        page_type="text",
        ruleset=ruleset,
        blocks=[],
    )
    return doc, rule, ctx


def test_id_card_outputs_avatar_and_number_not_whole_card(tmp_path):
    path = _card_pdf(tmp_path, pymupdf.Rect(100, 100, 300, 220), ID)
    doc, rule, ctx = _context(path)
    try:
        boxes = match_image(rule, ctx)
    finally:
        doc.close()

    notes = {box.note for box in boxes}
    assert len(boxes) == 2
    assert any("id_card_avatar" in note for note in notes)
    assert any("id_card_number" in note for note in notes)
    assert all(box.mode == "rect" for box in boxes)
    number_box = next(box for box in boxes if "id_card_number" in box.note)
    assert number_box.rect.y1 >= 200


def test_id_card_bottom_fallback_without_text(tmp_path):
    path = _card_pdf(tmp_path, pymupdf.Rect(100, 100, 300, 220), None)
    doc, rule, ctx = _context(path)
    try:
        boxes = match_image(rule, ctx)
    finally:
        doc.close()

    number_box = next(box for box in boxes if "id_card_number" in box.note)
    assert "id_card_number_bottom" in number_box.note
    assert number_box.rect.y0 > 180


def test_dual_id_card_split_into_two_cards(tmp_path):
    path = _card_pdf(tmp_path, pymupdf.Rect(100, 100, 500, 220), ID)
    doc, rule, ctx = _context(path)
    try:
        boxes = match_image(rule, ctx)
    finally:
        doc.close()

    assert len(boxes) == 4
    avatars = [box for box in boxes if "id_card_avatar" in box.note]
    assert len(avatars) == 2
    assert avatars[0].rect.x1 <= 300 <= avatars[1].rect.x0 + 1


def _card_with_pixmap(tmp_path, rect: pymupdf.Rect, pix: pymupdf.Pixmap) -> Path:
    path = tmp_path / "custom.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(rect, pixmap=pix)
    doc.save(path)
    doc.close()
    return path


def _pixmap(width: int, height: int, color=(220, 220, 220)) -> pymupdf.Pixmap:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), 0)
    pix.set_rect(pix.irect, color)
    return pix


def test_small_signature_is_not_treated_as_card(tmp_path):
    path = _card_with_pixmap(
        tmp_path, pymupdf.Rect(100, 100, 188, 131), _pixmap(40, 14)
    )
    doc, rule, ctx = _context(path)
    try:
        boxes = match_image(rule, ctx)
    finally:
        doc.close()
    assert boxes == []


def test_red_seal_is_not_treated_as_card(tmp_path):
    path = _card_with_pixmap(
        tmp_path, pymupdf.Rect(100, 100, 300, 220), _pixmap(40, 24, (210, 30, 30))
    )
    doc, rule, ctx = _context(path)
    try:
        boxes = match_image(rule, ctx)
    finally:
        doc.close()
    assert boxes == []


def test_id_card_back_is_skipped(tmp_path):
    pix = _pixmap(40, 24)
    pix.set_rect(pymupdf.IRect(2, 2, 10, 9), (210, 30, 30))
    path = _card_with_pixmap(tmp_path, pymupdf.Rect(100, 100, 300, 220), pix)
    doc, rule, ctx = _context(path)
    try:
        boxes = match_image(rule, ctx)
    finally:
        doc.close()
    assert boxes == []