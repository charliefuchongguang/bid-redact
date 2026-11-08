from __future__ import annotations

import pymupdf

from app.rules.box import Box
from app.rules.checks import verify as verify_value
from app.rules.matchers.base import MatchContext, iter_mineru_blocks, iter_text_lines
from app.rules.normalize import (
    extract_value_after,
    mineru_bbox_to_rect,
    normalize_ocr_text,
    text_span_bbox,
    text_span_bbox_uniform,
)
from app.rules.whitelist import whitelist_hit

MAX_KEYWORD_HITS = 3
MIN_TEXT_CHARS = 50


def match_semantic(rule: dict, ctx: MatchContext) -> list[Box]:
    match = rule.get("match") or {}
    keywords = match.get("keywords") or []
    value_pattern = match.get("value_pattern") or match.get("pattern_after")
    scope = match.get("scope", "after")
    max_len = int(match.get("max_len", 60))
    on = match.get("on", "auto")

    text_body = ctx.text.strip()
    use_text = ctx.page_type == "text" and len(text_body) >= MIN_TEXT_CHARS
    if on == "mineru":
        use_text = False
    elif on == "text":
        use_text = bool(text_body)
    elif not use_text and not ctx.blocks:
        use_text = bool(text_body)

    boxes: list[Box] = []
    if use_text:
        for text, bbox in iter_text_lines(ctx):
            boxes.extend(
                _process(rule, ctx, text, bbox, keywords, value_pattern, scope, max_len, source="text")
            )
        return boxes

    canvas = float(ctx.config.get("mineru_canvas", 1000))
    for block, text in iter_mineru_blocks(ctx):
        bbox = block.get("bbox")
        if not bbox:
            continue
        norm, index_map = normalize_ocr_text(text)
        boxes.extend(
            _process(
                rule,
                ctx,
                norm,
                bbox,
                keywords,
                value_pattern,
                scope,
                max_len,
                source="mineru",
                canvas=canvas,
                index_map=index_map,
                orig_text=text,
            )
        )
    return boxes


def _to_page(ctx: MatchContext, bbox: list[float], source: str, canvas: float) -> pymupdf.Rect:
    if source == "text":
        return pymupdf.Rect(bbox)
    return mineru_bbox_to_rect(ctx.page_rect, bbox, canvas)


def _process(
    rule: dict,
    ctx: MatchContext,
    text: str,
    bbox: list[float],
    keywords: list[str],
    value_pattern: str | None,
    scope: str,
    max_len: int,
    source: str,
    canvas: float = 1000.0,
    index_map: list[int] | None = None,
    orig_text: str | None = None,
) -> list[Box]:
    match = rule.get("match") or {}
    excludes = match.get("exclude_context") or []
    if any(k in text for k in excludes):
        return []
    verify_kind = match.get("verify")

    boxes: list[Box] = []
    for keyword in keywords:
        start_at = 0
        hits = 0
        while hits < MAX_KEYWORD_HITS:
            idx = text.find(keyword, start_at)
            if idx == -1:
                break
            hits += 1
            start_at = idx + len(keyword)

            if scope == "block":
                value = text.strip()
                if value and not whitelist_hit(value, text, rule, ctx.ruleset):
                    rect = _to_page(ctx, bbox, source, canvas)
                    boxes.append(ctx.make_box(rule, rect, value, source=source, note="block"))
                continue

            extracted = extract_value_after(text, idx + len(keyword), value_pattern, max_len)
            if not extracted:
                continue
            value, v_start, v_end = extracted
            if not value or (verify_kind and not verify_value(verify_kind, value)):
                continue
            if whitelist_hit(value, text, rule, ctx.ruleset):
                continue

            if source == "text":
                rects = _search_same_line(ctx, value, bbox)
                if rects:
                    for rect in rects:
                        boxes.append(ctx.make_box(rule, rect, value, source="text", note="after"))
                    continue

            if source == "text":
                sub = text_span_bbox(bbox, text, v_start, v_end)
            else:
                raw = orig_text if orig_text is not None else text
                if index_map:
                    o_start = index_map[v_start]
                    o_end = index_map[v_end - 1] + 1
                else:
                    o_start, o_end = v_start, v_end
                sub = text_span_bbox_uniform(bbox, raw, o_start, o_end)
            rect = _to_page(ctx, sub, source, canvas)
            boxes.append(ctx.make_box(rule, rect, value, source=source, note="after"))
    return boxes


def _search_same_line(ctx: MatchContext, value: str, line_bbox: list[float]) -> list[pymupdf.Rect]:
    line_y = (line_bbox[1] + line_bbox[3]) / 2
    tolerance = max(6.0, (line_bbox[3] - line_bbox[1]) * 0.6)
    found = []
    for rect in ctx.page.search_for(value):
        if abs((rect.y0 + rect.y1) / 2 - line_y) <= tolerance:
            found.append(rect)
    return found