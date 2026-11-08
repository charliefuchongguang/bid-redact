from __future__ import annotations

import re

import pymupdf

from app.rules.box import Box
from app.rules.checks import gb11643_valid
from app.rules.matchers.base import MatchContext, iter_text_lines
from app.rules.normalize import clamp, mineru_bbox_to_rect

ID_RE = re.compile(r"(?<![0-9A-Za-z])[1-9]\d{16}[0-9Xx](?![0-9A-Za-z])")

AVATAR_REGION = (0.59, 0.15, 0.93, 0.80)
NUMBER_REGION = (0.06, 0.78, 0.98, 0.99)
BACK_REGION = (0.03, 0.62, 0.97, 1.0)
MIN_CARD_WIDTH = 120.0
MIN_CARD_HEIGHT = 70.0

BACK_FIELDS = ("签发机关", "有效期限")
STRONG_BACK_CONTEXT = (
    "签发机关",
    "有效期限",
    "公民身份号码",
    "居民身份证",
    "身份证正反面",
    "身份证正、反面",
    "身份证复印件",
    "有效身份证",
    "身份证明",
)
CERT_CONTEXT = (
    "毕业证书",
    "学位证书",
    "职称证书",
    "注册执业证书",
    "注册证书",
    "执业证书",
    "资格证书",
    "营业执照",
    "资质证书",
    "审查合格书",
    "中标通知书",
    "普通高等学校",
    "准予毕业",
    "研究生",
    "学制",
    "培养单位",
    "校长",
    "校(院、所)长",
    "教育部",
    "学信网",
    "查询网址",
    "证书编号",
)
ID_CARD_HINTS = ("公民身份号码", "住址", "民族", "签发机关", "有效期限")


def match_image(rule: dict, ctx: MatchContext) -> list[Box]:
    match = rule.get("match") or {}
    detect = match.get("detect")
    if detect != "id_card":
        return []

    min_aspect = float(match.get("min_aspect", 1.25))
    max_aspect = float(match.get("max_aspect", 2.0))
    max_area_ratio = float(match.get("max_page_area_ratio", 0.45))
    page_area = ctx.page_rect.width * ctx.page_rect.height
    boxes: list[Box] = []

    candidates: list[tuple[pymupdf.Rect, str]] = []
    try:
        for info in ctx.page.get_image_info(xrefs=True):
            bbox = info.get("bbox")
            if bbox:
                candidates.append((pymupdf.Rect(bbox), "image"))
    except Exception:
        pass

    canvas = float(ctx.config.get("mineru_canvas", 1000))
    for block in ctx.blocks:
        if block.get("type") != "image":
            continue
        bbox = block.get("bbox")
        if not bbox:
            continue
        candidates.append((mineru_bbox_to_rect(ctx.page_rect, bbox, canvas), "mineru"))

    seen: list[pymupdf.Rect] = []
    for rect, source in candidates:
        if rect.is_empty or rect.width < MIN_CARD_WIDTH or rect.height < MIN_CARD_HEIGHT:
            continue
        if any(abs(rect.x0 - s.x0) < 1 and abs(rect.y0 - s.y0) < 1 for s in seen):
            continue
        area_ratio = rect.get_area() / page_area if page_area else 1
        if area_ratio > max_area_ratio:
            continue
        aspect = rect.width / rect.height
        ok = min_aspect <= aspect <= max_aspect
        if not ok and 2.4 <= aspect <= 3.8 and rect.height <= 190:
            ok = True
        if not ok and 0.60 <= aspect <= 0.95 and _strong_back_context(ctx):
            ok = True
        if not ok:
            continue
        seen.append(rect)
        try:
            boxes.extend(_id_card_boxes(rule, ctx, rect, source))
        except Exception:
            boxes.append(
                ctx.make_box(
                    rule,
                    rect,
                    "",
                    source=source,
                    confidence=float(rule.get("confidence", 0.9)),
                    state="pending",
                    note="id_card_fallback",
                )
            )
    return boxes


def _id_card_boxes(rule: dict, ctx: MatchContext, card: pymupdf.Rect, source: str) -> list[Box]:
    cards = _split_cards(card)
    tall_split = len(cards) == 2 and card.height > card.width
    boxes: list[Box] = []
    text_items = _text_items(ctx)
    page_context = _strong_back_context(ctx)
    page_area = ctx.page_rect.width * ctx.page_rect.height
    for item in cards:
        if item.is_empty or item.width < MIN_CARD_WIDTH or item.height < MIN_CARD_HEIGHT:
            continue
        card_text = _text_in_rect(text_items, item)
        if any(keyword in card_text for keyword in CERT_CONTEXT):
            area_ratio = item.get_area() / page_area if page_area else 1.0
            if area_ratio > 0.10:
                boxes.extend(
                    _cert_number_fallback(
                        ctx, item, include_school=not _has_number_text(card_text)
                    )
                )
            continue
        area_ratio = item.get_area() / page_area if page_area else 1.0
        if ctx.face_detection:
            face = _has_face(ctx.faces, item)
            has_back = any(keyword in card_text for keyword in BACK_FIELDS)
            if face:
                if not _is_id_like(item):
                    continue
                if card_text and not any(hint in card_text for hint in ID_CARD_HINTS):
                    if area_ratio > 0.10:
                        boxes.extend(
                            _cert_number_fallback(
                                ctx, item, include_school=not _has_number_text(card_text)
                            )
                        )
                    continue
                if not card_text and tall_split:
                    continue
                if not card_text and len(cards) == 1 and area_ratio > 0.20:
                    boxes.extend(_cert_number_fallback(ctx, item, include_school=True))
                    continue
                boxes.extend(_front_boxes(rule, ctx, item, source, text_items))
                continue
            if not _is_id_like(item) or not (has_back or page_context):
                continue
            if tall_split and not card_text and not has_back:
                continue
            if area_ratio > (0.35 if has_back else 0.20):
                continue
            note = "id_card_back" if has_back else "id_card_back_inferred"
            boxes.append(
                ctx.make_box(
                    rule,
                    _region(item, BACK_REGION),
                    "",
                    source=source,
                    confidence=0.9 if has_back else 0.72,
                    note=note,
                    mode="rect",
                )
            )
            continue
        if _is_seal_or_back(ctx.page, item):
            continue
        boxes.extend(_front_boxes(rule, ctx, item, source, text_items))
    return boxes


def _front_boxes(
    rule: dict,
    ctx: MatchContext,
    item: pymupdf.Rect,
    source: str,
    text_items: list[tuple[str, pymupdf.Rect]],
) -> list[Box]:
    avatar_box = ctx.make_box(
        rule,
        _region(item, AVATAR_REGION),
        "",
        source=source,
        confidence=float(rule.get("confidence", 0.9)),
        note="id_card_avatar",
        mode="rect",
    )
    number_rect, verified = _number_rect(ctx, item, text_items)
    number_box = ctx.make_box(
        rule,
        number_rect,
        "",
        source=source,
        confidence=0.95 if verified else 0.85,
        note="id_card_number" if verified else "id_card_number_bottom",
        mode="rect",
    )
    return [avatar_box, number_box]


def _has_number_text(card_text: str) -> bool:
    return any(keyword in card_text for keyword in ("证书编号", "学校编号", "No.", "NO."))


def _cert_number_fallback(
    ctx: MatchContext, card: pymupdf.Rect, *, include_school: bool = True
) -> list[Box]:
    """证书 OCR 未识别编号时，兜底遮挡底部 No./证书编号/学校编号区域。"""
    regions = [(0.02, 0.86, 0.42, 1.0)]
    if include_school:
        regions.append((0.50, 0.84, 0.99, 1.0))
    boxes: list[Box] = []
    for region in regions:
        rect = clamp(_region(card, region), ctx.page_rect)
        boxes.append(
            Box(
                page=ctx.page_no,
                rect=rect,
                category="personal",
                rule_id="RED-25",
                mode="rect",
                source="image_fallback",
                confidence=0.6,
                value="",
                state="pending",
                note="cert_number_fallback",
            )
        )
    return boxes


def _is_id_like(rect: pymupdf.Rect) -> bool:
    aspect = rect.width / rect.height if rect.height else 0
    return 1.3 <= aspect <= 1.85


def _strong_back_context(ctx: MatchContext) -> bool:
    page_text = ctx.combined_text
    return any(keyword in page_text for keyword in STRONG_BACK_CONTEXT)


def _text_items(ctx: MatchContext) -> list[tuple[str, pymupdf.Rect]]:
    items: list[tuple[str, pymupdf.Rect]] = []
    for text, bbox in iter_text_lines(ctx):
        if text.strip():
            items.append((text, pymupdf.Rect(bbox)))
    canvas = float(ctx.config.get("mineru_canvas", 1000))
    for block in ctx.blocks:
        text = str(block.get("text") or block.get("table_body") or "")
        bbox = block.get("bbox")
        if not text.strip() or not bbox:
            continue
        items.append((text, mineru_bbox_to_rect(ctx.page_rect, bbox, canvas)))
    return items


def _text_in_rect(items: list[tuple[str, pymupdf.Rect]], rect: pymupdf.Rect) -> str:
    parts: list[str] = []
    for text, text_rect in items:
        inter = text_rect & rect
        if inter.is_empty:
            continue
        center = pymupdf.Point((text_rect.x0 + text_rect.x1) / 2, (text_rect.y0 + text_rect.y1) / 2)
        if rect.contains(center) or inter.get_area() >= text_rect.get_area() * 0.5:
            parts.append(text)
    return " ".join(parts)


def _split_cards(rect: pymupdf.Rect) -> list[pymupdf.Rect]:
    aspect = rect.width / rect.height if rect.height else 0
    if aspect >= 2.4:
        mid = (rect.x0 + rect.x1) / 2
        return [
            pymupdf.Rect(rect.x0, rect.y0, mid, rect.y1),
            pymupdf.Rect(mid, rect.y0, rect.x1, rect.y1),
        ]
    if aspect <= 0.95:
        mid = (rect.y0 + rect.y1) / 2
        return [
            pymupdf.Rect(rect.x0, rect.y0, rect.x1, mid),
            pymupdf.Rect(rect.x0, mid, rect.x1, rect.y1),
        ]
    return [rect]


def _has_face(faces: list[pymupdf.Rect], card: pymupdf.Rect) -> bool:
    for face in faces:
        center = pymupdf.Point(
            (face.x0 + face.x1) / 2,
            (face.y0 + face.y1) / 2,
        )
        if card.contains(center):
            return True
    return False


def _is_seal_or_back(page: pymupdf.Page, rect: pymupdf.Rect) -> bool:
    """排除公章误识别和身份证背面，避免把非头像/号码区域涂黑。"""
    evidence = _image_evidence(page, rect)
    if evidence is None:
        return False
    red, photo_dark, top_left_red = evidence
    if red > 0.10 and photo_dark < 0.03:
        return True
    if top_left_red > 0.15 and photo_dark < 0.08:
        return True
    return False


def _image_evidence(
    page: pymupdf.Page, rect: pymupdf.Rect
) -> tuple[float, float, float] | None:
    try:
        pix = page.get_pixmap(
            dpi=100, clip=rect, colorspace=pymupdf.csRGB, alpha=False
        )
    except Exception:
        return None
    width, height = pix.width, pix.height
    if width < 8 or height < 8:
        return None

    samples = pix.samples
    stride = pix.n
    total = width * height
    red = 0
    photo_dark = 0
    photo_total = 0
    top_left_red = 0
    top_left_total = 0

    x_photo0, x_photo1 = int(width * 0.60), int(width * 0.95)
    y_photo0, y_photo1 = int(height * 0.10), int(height * 0.85)
    x_tl, y_tl = int(width * 0.35), int(height * 0.50)

    for y in range(height):
        row = y * width
        for x in range(width):
            i = (row + x) * stride
            r, g, b = samples[i], samples[i + 1], samples[i + 2]
            is_red = r > 150 and (r - g) > 50 and (r - b) > 50
            if is_red:
                red += 1
            if x < x_tl and y < y_tl:
                top_left_total += 1
                if is_red:
                    top_left_red += 1
            if x_photo0 <= x < x_photo1 and y_photo0 <= y < y_photo1:
                photo_total += 1
                if r < 100 and g < 100 and b < 100:
                    photo_dark += 1

    return (
        red / total if total else 0.0,
        photo_dark / photo_total if photo_total else 0.0,
        top_left_red / top_left_total if top_left_total else 0.0,
    )


def _region(rect: pymupdf.Rect, region: tuple[float, float, float, float]) -> pymupdf.Rect:
    x0, y0, x1, y1 = region
    width = rect.width
    height = rect.height
    return pymupdf.Rect(
        rect.x0 + width * x0,
        rect.y0 + height * y0,
        rect.x0 + width * x1,
        rect.y0 + height * y1,
    )


def _number_rect(
    ctx: MatchContext,
    card: pymupdf.Rect,
    text_items: list[tuple[str, pymupdf.Rect]] | None = None,
) -> tuple[pymupdf.Rect, bool]:
    """优先用文本层/MinerU 文本中的 18 位身份证号；否则遮整条底部。"""
    for text, text_rect in text_items or []:
        for value in ID_RE.findall(text):
            if not gb11643_valid(value):
                continue
            center = pymupdf.Point(
                (text_rect.x0 + text_rect.x1) / 2, (text_rect.y0 + text_rect.y1) / 2
            )
            if card.contains(center):
                return clamp(text_rect, ctx.page_rect), True
    try:
        text = ctx.page.get_text("text")
    except Exception:
        text = ""
    for value in ID_RE.findall(text):
        if not gb11643_valid(value):
            continue
        for found in ctx.page.search_for(value):
            if card.contains(found) or (found & card).get_area() >= found.get_area() * 0.8:
                return clamp(found, ctx.page_rect), True
    return clamp(_region(card, NUMBER_REGION), ctx.page_rect), False