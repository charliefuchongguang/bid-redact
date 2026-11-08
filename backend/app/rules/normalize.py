from __future__ import annotations

import re
import unicodedata

import pymupdf


_PUNCT_MAP = {
    "，": ",",
    "。": ".",
    "、": ",",
    "；": ";",
    "：": ":",
    "！": "!",
    "？": "?",
    "（": "(",
    "）": ")",
    "【": "[",
    "】": "]",
    "《": "<",
    "》": ">",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "－": "-",
    "—": "-",
    "–": "-",
    "￥": "¥",
}


def normalize_ocr_text(text: str) -> tuple[str, list[int]]:
    """OCR 文本归一化：全角转半角、中文标点转 ASCII、去掉所有空白。

    返回 (归一化文本, 每个归一化字符对应的原始下标)。
    """
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if ch.isspace() or ch == "\u3000":
            continue
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            ch = chr(code - 0xFEE0)
        else:
            ch = _PUNCT_MAP.get(ch, ch)
        out.append(ch)
        index.append(i)
    return "".join(out), index


def char_weight(ch: str) -> float:
    if ch.isspace():
        return 0.6
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2.0
    return 1.0


def text_span_bbox(bbox: list[float] | tuple[float, ...], text: str, start: int, end: int) -> list[float]:
    """按字符宽度估算文本区间在 bbox 内的水平子区间。"""
    x0, y0, x1, y1 = bbox
    if not text:
        return [x0, y0, x1, y1]
    weights = [char_weight(c) for c in text]
    total = sum(weights) or 1.0
    before = sum(weights[:start])
    within = sum(weights[start:end])
    width = x1 - x0
    return [x0 + width * before / total, y0, x0 + width * (before + within) / total, y1]


def text_span_bbox_uniform(bbox: list[float] | tuple[float, ...], text: str, start: int, end: int) -> list[float]:
    """按字符数量等宽估算（适用于 OCR 文本块）。"""
    x0, y0, x1, y1 = bbox
    n = max(len(text), 1)
    width = x1 - x0
    return [x0 + width * start / n, y0, x0 + width * end / n, y1]


def mineru_bbox_to_rect(page_rect: pymupdf.Rect, bbox: list[float], canvas: float = 1000.0) -> pymupdf.Rect:
    """Mineru bbox（每页 0~canvas 归一化）-> PDF point。"""
    sx = page_rect.width / canvas
    sy = page_rect.height / canvas
    return pymupdf.Rect(
        page_rect.x0 + bbox[0] * sx,
        page_rect.y0 + bbox[1] * sy,
        page_rect.x0 + bbox[2] * sx,
        page_rect.y0 + bbox[3] * sy,
    )


def clamp(rect: pymupdf.Rect, page_rect: pymupdf.Rect) -> pymupdf.Rect:
    out = pymupdf.Rect(rect)
    out.x0 = max(out.x0, page_rect.x0)
    out.y0 = max(out.y0, page_rect.y0)
    out.x1 = min(out.x1, page_rect.x1)
    out.y1 = min(out.y1, page_rect.y1)
    if out.x1 <= out.x0:
        out.x1 = min(out.x0 + 1, page_rect.x1)
    if out.y1 <= out.y0:
        out.y1 = min(out.y0 + 1, page_rect.y1)
    return out


def pad_rect(rect: pymupdf.Rect, pad: float, page_rect: pymupdf.Rect) -> pymupdf.Rect:
    return clamp(
        pymupdf.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad),
        page_rect,
    )


def line_of_offset(text: str, start: int, end: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end]


def extract_value_after(text: str, keyword_end: int, value_pattern: str | None, max_len: int) -> tuple[str, int, int] | None:
    """从关键词之后提取值，返回 (value, start, end)。"""
    rest_start = keyword_end
    while rest_start < len(text) and (text[rest_start].isspace() or text[rest_start] in "：:，,、-—_"):
        rest_start += 1
    rest = text[rest_start:]
    if not rest:
        return None
    if value_pattern:
        m = re.search(value_pattern, rest)
        if not m:
            return None
        return m.group(0), rest_start + m.start(), rest_start + m.end()
    end = min(len(text), rest_start + max_len)
    nl = text.find("\n", rest_start, end)
    if nl != -1:
        end = nl
    value = text[rest_start:end].strip()
    if not value:
        return None
    actual_start = text.find(value, rest_start, end)
    if actual_start == -1:
        actual_start = rest_start
    return value, actual_start, actual_start + len(value)