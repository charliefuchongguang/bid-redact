from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf

from app.rules.box import Box
from app.rules.dedupe import dedupe
from app.rules.loader import RuleSet
from app.rules.matchers.base import MatchContext
from app.rules.matchers.image_matcher import match_image
from app.rules.matchers.regex_matcher import match_regex
from app.rules.matchers.semantic_matcher import match_semantic
from app.rules.matchers.table_matcher import match_table
from app.rules.normalize import clamp, mineru_bbox_to_rect

MATCHERS = {
    "regex": match_regex,
    "semantic": match_semantic,
    "table": match_table,
    "image": match_image,
}


@dataclass
class LocateResult:
    boxes: list[Box] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def locate(
    doc: pymupdf.Document,
    ruleset: RuleSet,
    blocks_by_page: dict[int, list[dict]] | None = None,
    page_types: list[str] | None = None,
    faces_by_page: dict[int, list[pymupdf.Rect]] | None = None,
    face_detection: bool = False,
) -> LocateResult:
    blocks_by_page = blocks_by_page or {}
    page_types = page_types or ["text"] * len(doc)
    faces_by_page = faces_by_page or {}
    result = LocateResult()
    rules = ruleset.enabled_rules()

    for page_no in range(len(doc)):
        ctx = MatchContext(
            doc=doc,
            page_no=page_no,
            page=doc[page_no],
            page_type=page_types[page_no],
            ruleset=ruleset,
            blocks=blocks_by_page.get(page_no, []),
            faces=faces_by_page.get(page_no, []),
            face_detection=face_detection,
        )
        for rule in rules:
            matcher = MATCHERS.get((rule.get("match") or {}).get("type"))
            if not matcher:
                continue
            if _page_skipped(rule, ctx):
                continue
            try:
                found = matcher(rule, ctx)
            except Exception as exc:  # 单条规则失败不阻断整体
                result.errors.append(f"page={page_no} rule={rule.get('id')} {type(exc).__name__}: {exc}")
                continue
            if found:
                result.stats[rule["id"]] = result.stats.get(rule["id"], 0) + len(found)
                result.boxes.extend(found)

    _filter_image_boxes(doc, result.boxes, page_types)
    _expand_cards(doc, result.boxes, blocks_by_page, ruleset)
    result.boxes = dedupe(result.boxes)
    return result


def _page_skipped(rule: dict, ctx: MatchContext) -> bool:
    keywords = rule.get("skip_page_keywords") or []
    if not keywords:
        return False
    page_text = ctx.combined_text
    return any(keyword in page_text for keyword in keywords)


def _filter_image_boxes(doc: pymupdf.Document, boxes: list[Box], page_types: list[str]) -> None:
    """文本页上的“身份证图片”需有身份证号或“身份证”文字佐证，避免误伤 logo。"""
    id_pages = {b.page for b in boxes if b.rule_id == "RED-01"}
    kept = []
    for box in boxes:
        if box.rule_id == "RED-02" and page_types[box.page] == "text" and box.page not in id_pages:
            text = doc[box.page].get_text("text")
            if "身份证" not in text:
                continue
        kept.append(box)
    boxes[:] = kept


def _expand_cards(
    doc: pymupdf.Document,
    boxes: list[Box],
    blocks_by_page: dict[int, list[dict]],
    ruleset: RuleSet,
) -> None:
    canvas = float(ruleset.global_cfg.get("mineru_canvas", 1000))
    p5_pages = {
        box.page
        for box in boxes
        if box.rule_id == "RED-02" and "id_card_avatar" in (box.note or "")
    }
    for box in boxes:
        if box.mode != "card":
            continue
        if box.page in p5_pages:
            box.mode = "rect"
            box.note = f"{box.note}; card=skip_p5" if box.note else "card=skip_p5"
            continue
        page = doc[box.page]
        page_rect = page.rect
        page_area = page_rect.width * page_rect.height
        center = pymupdf.Point((box.rect.x0 + box.rect.x1) / 2, (box.rect.y0 + box.rect.y1) / 2)

        candidates: list[pymupdf.Rect] = []
        try:
            for info in page.get_image_info(xrefs=True):
                bbox = info.get("bbox")
                if not bbox:
                    continue
                rect = pymupdf.Rect(bbox)
                if _id_card_boundary(rect, center, page_area):
                    candidates.append(rect)
        except Exception:
            pass

        for block in blocks_by_page.get(box.page, []):
            if block.get("type") != "image" or not block.get("bbox"):
                continue
            rect = mineru_bbox_to_rect(page_rect, block["bbox"], canvas)
            if _id_card_boundary(rect, center, page_area):
                candidates.append(rect)

        if candidates:
            best = min(candidates, key=lambda r: r.get_area())
            box.rect = clamp(best | box.rect, page_rect)
            box.note = f"{box.note}; card=expanded" if box.note else "card=expanded"
        else:
            box.note = f"{box.note}; card=no_boundary" if box.note else "card=no_boundary"


def _id_card_boundary(rect: pymupdf.Rect, center: pymupdf.Point, page_area: float) -> bool:
    """只允许身份证卡片尺寸的图片参与整卡扩展，避免吞掉整页扫描件/社保证明。"""
    if not rect.contains(center) or rect.is_empty:
        return False
    if page_area and rect.get_area() > page_area * 0.35:
        return False
    aspect = rect.width / rect.height if rect.height else 0
    return 1.1 <= aspect <= 2.4