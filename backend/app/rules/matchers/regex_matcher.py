from __future__ import annotations

import pymupdf

from app.rules.box import Box
from app.rules.checks import verify
from app.rules.loader import compile_pattern
from app.rules.matchers.base import MatchContext, iter_mineru_blocks
from app.rules.normalize import (
    line_of_offset,
    mineru_bbox_to_rect,
    normalize_ocr_text,
    text_span_bbox_uniform,
)
from app.rules.whitelist import whitelist_hit

MAX_HITS_PER_RULE = 200
MIN_TEXT_CHARS = 50


def match_regex(rule: dict, ctx: MatchContext) -> list[Box]:
    match = rule.get("match") or {}
    pattern = compile_pattern(match["pattern"])
    verify_kind = match.get("verify")
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
        text = ctx.text
        for m in pattern.finditer(text):
            if len(boxes) >= MAX_HITS_PER_RULE:
                break
            value = m.group(0)
            if not verify(verify_kind, value):
                continue
            context = line_of_offset(text, m.start(), m.end())
            if _excluded(context, rule) or whitelist_hit(value, context, rule, ctx.ruleset):
                continue
            for rect in _search(page=ctx.page, value=value):
                boxes.append(ctx.make_box(rule, rect, value, source="text"))
        return boxes

    for block, text in iter_mineru_blocks(ctx):
        if len(boxes) >= MAX_HITS_PER_RULE:
            break
        if _excluded(text, rule):
            continue
        norm, index_map = normalize_ocr_text(text)
        for m in pattern.finditer(norm):
            value = m.group(0)
            if not value or not verify(verify_kind, value):
                continue
            if whitelist_hit(value, norm, rule, ctx.ruleset):
                continue
            bbox = block.get("bbox")
            if not bbox:
                continue
            orig_start = index_map[m.start()]
            orig_end = index_map[m.end() - 1] + 1
            sub = text_span_bbox_uniform(bbox, text, orig_start, orig_end)
            rect = mineru_bbox_to_rect(
                ctx.page_rect, sub, float(ctx.config.get("mineru_canvas", 1000))
            )
            boxes.append(ctx.make_box(rule, rect, value, source="mineru"))
    return boxes


def _excluded(context: str, rule: dict) -> bool:
    excludes = (rule.get("match") or {}).get("exclude_context") or []
    return any(k in context for k in excludes)


def _search(page: pymupdf.Page, value: str) -> list[pymupdf.Rect]:
    rects = page.search_for(value)
    if rects:
        return rects
    compact = value.replace(" ", "")
    if compact != value:
        return page.search_for(compact)
    return []