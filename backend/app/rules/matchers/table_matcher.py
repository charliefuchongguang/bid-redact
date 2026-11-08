from __future__ import annotations

import html as html_lib
import re

import pymupdf

from app.rules.box import Box
from app.rules.loader import compile_pattern
from app.rules.matchers.base import MatchContext
from app.rules.normalize import mineru_bbox_to_rect
from app.rules.whitelist import whitelist_hit


MIN_TEXT_CHARS = 50


def match_table(rule: dict, ctx: MatchContext) -> list[Box]:
    on = (rule.get("match") or {}).get("on", "auto")
    if on == "mineru":
        return _scan_tables(rule, ctx)
    if on == "text":
        return _text_tables(rule, ctx)
    if ctx.page_type == "text" and len(ctx.text.strip()) >= MIN_TEXT_CHARS:
        return _text_tables(rule, ctx)
    if ctx.blocks:
        return _scan_tables(rule, ctx)
    return _text_tables(rule, ctx)


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _text_tables(rule: dict, ctx: MatchContext) -> list[Box]:
    match = rule.get("match") or {}
    headers = match.get("column_headers") or []
    row_keywords = match.get("row_keywords") or []
    value_re = compile_pattern(match.get("value_pattern", r"\d"))
    boxes: list[Box] = []
    try:
        finder = ctx.page.find_tables()
    except Exception:
        return boxes
    if match.get("scan_all_cells"):
        return _text_scan_all_cells(rule, ctx, finder, headers, value_re)

    words = ctx.page.get_text("words")
    for table in finder.tables:
        try:
            data = table.extract()
            rows = table.rows
            table_bbox = table.bbox
        except Exception:
            continue
        if not data or not rows:
            continue
        if row_keywords:
            boxes.extend(
                _text_label_values(
                    rule, ctx, words, table_bbox, rows, data, row_keywords, value_re
                )
            )
            continue
        header_row = [_norm(c) for c in data[0]]
        col_idx = [
            i for i, name in enumerate(header_row)
            if any(h in name for h in headers)
        ]
        if not col_idx:
            continue
        for r_i in range(1, min(len(rows), len(data))):
            row = rows[r_i]
            cells = getattr(row, "cells", None)
            if not cells:
                continue
            values = data[r_i]
            line_ctx = " ".join(str(v) for v in values if v)
            for ci in col_idx:
                if ci >= len(cells) or cells[ci] is None:
                    continue
                value = str(values[ci] or "").strip() if ci < len(values) else ""
                if not value or not value_re.search(value):
                    continue
                if whitelist_hit(value, line_ctx, rule, ctx.ruleset):
                    continue
                cell_rect = pymupdf.Rect(cells[ci])
                x_end = _column_right(cells, ci, table_bbox, ctx.page_rect)
                merged = _union_row_words(words, cell_rect, x_end)
                boxes.append(
                    ctx.make_box(rule, merged, value, source="text", note="cell")
                )
    return boxes


def _text_scan_all_cells(rule, ctx, finder, headers: list[str], value_re) -> list[Box]:
    boxes: list[Box] = []
    words = ctx.page.get_text("words")
    for table in finder.tables:
        try:
            data = table.extract()
            rows = table.rows
            table_bbox = table.bbox
        except Exception:
            continue
        if not data or not rows:
            continue
        header_rows = [
            r_i
            for r_i, values in enumerate(data)
            if any(
                any(header in _norm(str(value or "")) for header in headers)
                for value in values
            )
        ]
        if not header_rows:
            continue
        start = min(header_rows)
        seen: set[tuple[int, int]] = set()
        for r_i in range(start, min(len(rows), len(data))):
            row = rows[r_i]
            cells = getattr(row, "cells", None)
            if not cells:
                continue
            values = data[r_i]
            for ci, raw in enumerate(values):
                if ci >= len(cells) or cells[ci] is None:
                    continue
                value = str(raw or "").strip()
                if not value or not value_re.search(value):
                    continue
                if (r_i, ci) in seen:
                    continue
                line_ctx = " ".join(str(v) for v in values if v)
                if whitelist_hit(value, line_ctx, rule, ctx.ruleset):
                    continue
                seen.add((r_i, ci))
                cell_rect = pymupdf.Rect(cells[ci])
                x_end = _column_right(cells, ci, table_bbox, ctx.page_rect)
                merged = _union_row_words(words, cell_rect, x_end)
                boxes.append(
                    ctx.make_box(
                        rule,
                        merged,
                        value,
                        source="text",
                        note="table_scan_cell",
                    )
                )
    return boxes


def _text_label_values(
    rule: dict,
    ctx: MatchContext,
    words,
    table_bbox,
    rows,
    data,
    row_keywords: list[str],
    value_re,
) -> list[Box]:
    boxes: list[Box] = []
    positions = _positions(rule)
    seen: set[tuple[int, int]] = set()
    for r_i in range(min(len(rows), len(data))):
        cells = getattr(rows[r_i], "cells", None)
        if not cells:
            continue
        values = data[r_i]
        for ci, raw in enumerate(values):
            label = _norm(str(raw or ""))
            if not label or ci >= len(cells) or cells[ci] is None:
                continue
            if not any(keyword in label for keyword in row_keywords):
                continue
            found = _pick_text_target(
                rule,
                ctx,
                rows,
                data,
                table_bbox,
                words,
                r_i,
                ci,
                positions,
                value_re,
                seen,
            )
            if found is not None:
                boxes.append(found)
    return boxes


def _pick_text_target(
    rule, ctx, rows, data, table_bbox, words, row_i, col_i, positions, value_re, seen
):
    label_cells = getattr(rows[row_i], "cells", None)
    for position in positions:
        target = _target_cell(label_cells, data, row_i, col_i, position)
        if target is None or target in seen:
            continue
        t_row, t_ci = target
        target_cells = getattr(rows[t_row], "cells", None)
        if not target_cells or t_ci >= len(target_cells) or target_cells[t_ci] is None:
            continue
        value = str(data[t_row][t_ci] or "").strip()
        if not value or not value_re.search(value):
            continue
        line_ctx = " ".join(str(v) for v in data[t_row] if v)
        if whitelist_hit(value, line_ctx, rule, ctx.ruleset):
            continue
        seen.add(target)
        cell_rect = pymupdf.Rect(target_cells[t_ci])
        x_end = _column_right(target_cells, t_ci, table_bbox, ctx.page_rect)
        merged = _union_row_words(words, cell_rect, x_end)
        return ctx.make_box(rule, merged, value, source="text", note=f"table_{position}")
    return None


def _positions(rule: dict) -> list[str]:
    match = rule.get("match") or {}
    positions = match.get("value_positions")
    if positions:
        return list(positions)
    return [match.get("value_position", "right")]


def _target_cell(cells, data, row_i: int, col_i: int, position: str) -> tuple[int, int] | None:
    if position == "same":
        return row_i, col_i
    if position == "below":
        next_row = row_i + 1
        if next_row < len(data) and col_i < len(data[next_row]):
            return next_row, col_i
        return None
    for ci in range(col_i + 1, len(data[row_i])):
        if ci < len(cells) and cells[ci] is not None and str(data[row_i][ci] or "").strip():
            return row_i, ci
    return None


def _column_right(cells, ci: int, table_bbox, page_rect: pymupdf.Rect) -> float:
    for j in range(ci + 1, len(cells)):
        if cells[j] is not None:
            return pymupdf.Rect(cells[j]).x0
    cell = pymupdf.Rect(cells[ci])
    table_right = pymupdf.Rect(table_bbox).x1
    # 最后一列：允许覆盖到页面右侧，防止文本溢出表格
    return min(page_rect.x1 - 20.0, max(table_right + 80.0, cell.x1))


def _union_row_words(words, cell_rect: pymupdf.Rect, x_end: float) -> pymupdf.Rect:
    merged = pymupdf.Rect(cell_rect)
    y_tol = 1.5
    for x0, y0, x1, y1, _text, *_rest in words:
        if y1 < cell_rect.y0 - y_tol or y0 > cell_rect.y1 + y_tol:
            continue
        if x0 < cell_rect.x0 - 1:
            continue
        if x0 > x_end:
            continue
        merged |= pymupdf.Rect(x0, y0, x1, y1)
    return merged


def _scan_tables(rule: dict, ctx: MatchContext) -> list[Box]:
    match = rule.get("match") or {}
    headers = match.get("column_headers") or []
    row_keywords = match.get("row_keywords") or []
    value_re = compile_pattern(match.get("value_pattern", r"\d"))
    canvas = float(ctx.config.get("mineru_canvas", 1000))
    boxes: list[Box] = []

    for block in ctx.blocks:
        if block.get("type") != "table":
            continue
        bbox = block.get("bbox")
        if not bbox:
            continue
        html = block.get("table_body") or ""
        if match.get("scan_all_cells"):
            boxes.extend(_scan_all_cells(rule, ctx, bbox, html, canvas))
            continue
        rows = _parse_html_table(html) if html else []
        if not rows:
            continue
        ncols = max(len(r) for r in rows)
        nrows = len(rows)
        if ncols == 0 or nrows == 0:
            continue
        x0, y0, x1, y1 = bbox
        cw = (x1 - x0) / ncols
        ch = (y1 - y0) / nrows

        if row_keywords:
            boxes.extend(
                _scan_label_values(
                    rule,
                    ctx,
                    bbox,
                    rows,
                    row_keywords,
                    value_re,
                    canvas,
                    cw,
                    ch,
                )
            )
            continue

        header_row = [_norm(c) for c in rows[0]]
        col_idx = [i for i, name in enumerate(header_row) if any(h in name for h in headers)]
        if not col_idx:
            continue

        for r_i in range(1, nrows):
            values = rows[r_i]
            line_ctx = " ".join(values)
            for ci in col_idx:
                if ci >= len(values):
                    continue
                value = values[ci].strip()
                if not value or not value_re.search(value):
                    continue
                if whitelist_hit(value, line_ctx, rule, ctx.ruleset):
                    continue
                cell_bbox = [x0 + ci * cw, y0 + r_i * ch, x0 + (ci + 1) * cw, y0 + (r_i + 1) * ch]
                rect = mineru_bbox_to_rect(ctx.page_rect, cell_bbox, canvas)
                boxes.append(
                    ctx.make_box(
                        rule,
                        rect,
                        value,
                        source="mineru",
                        confidence=min(float(rule.get("confidence", 0.8)), 0.65),
                        state="pending",
                        note="table_grid_approx",
                    )
                )
    return boxes


def _scan_all_cells(
    rule: dict,
    ctx: MatchContext,
    table_bbox,
    html: str,
    canvas: float,
) -> list[Box]:
    """在包含指定表头的表格中，扫描所有单元格值（兼容 rowspan/colspan）。"""
    match = rule.get("match") or {}
    headers = match.get("column_headers") or []
    value_re = compile_pattern(match.get("value_pattern", r"\d"))
    cells, nrows, ncols = _parse_html_cells(html)
    if not cells or nrows == 0 or ncols == 0:
        return []
    header_rows = [
        cell["r"]
        for cell in cells
        if headers and any(h in _norm(cell["text"]) for h in headers)
    ]
    if not header_rows:
        return []

    x0, y0, x1, y1 = table_bbox
    cw = (x1 - x0) / ncols
    ch = (y1 - y0) / nrows
    start = min(header_rows)
    row_cells: dict[int, list[dict]] = {}
    for cell in cells:
        row_cells.setdefault(cell["r"], []).append(cell)
    row_ends = {
        row: max(cell["c"] + cell["cs"] for cell in items)
        for row, items in row_cells.items()
    }

    groups: dict[tuple[int, int], list[dict]] = {}
    for cell in cells:
        if cell["r"] < start:
            continue
        if not any(h in _norm(cell["text"]) for h in headers):
            continue
        groups.setdefault((cell["c"], cell["cs"]), []).append(cell)

    boxes: list[Box] = []
    for (col_start, colspan), header_cells in groups.items():
        header_text = " ".join(cell["text"] for cell in header_cells)
        if any(keyword in header_text for keyword in ("电话", "联系")):
            col_start = max(0, ncols - min(3, ncols))
            colspan = ncols - col_start
        first_row = min(cell["r"] for cell in header_cells)
        end_row = nrows
        for row in range(first_row + 1, nrows):
            items = row_cells.get(row, [])
            if len(items) == 1 and row_ends.get(row, 0) >= ncols * 0.7:
                end_row = row
                break
        values = []
        for cell in cells:
            if not (first_row <= cell["r"] < end_row):
                continue
            if cell["c"] < col_start or cell["c"] >= col_start + colspan:
                continue
            text = cell["text"].strip()
            if not text or not value_re.search(text):
                continue
            if whitelist_hit(text, text, rule, ctx.ruleset):
                continue
            values.append(text)
        if not values:
            continue
        pad_x = 10.0
        pad_top = 2.0
        pad_bottom = 14.0
        column_bbox = [
            x0 + col_start * cw - pad_x,
            y0 + first_row * ch - pad_top,
            x0 + (col_start + colspan) * cw + pad_x,
            y0 + end_row * ch + pad_bottom,
        ]
        rect = mineru_bbox_to_rect(ctx.page_rect, column_bbox, canvas)
        boxes.append(
            ctx.make_box(
                rule,
                rect,
                " ".join(values),
                source="mineru",
                confidence=min(float(rule.get("confidence", 0.8)), 0.72),
                state="pending",
                note="table_column_scan",
            )
        )
    return boxes


def _parse_html_cells(html: str) -> tuple[list[dict], int, int]:
    rows = _TR_RE.findall(html or "")
    occupied: set[tuple[int, int]] = set()
    cells: list[dict] = []
    max_col = 0
    for r_index, tr in enumerate(rows):
        col = 0
        for attrs, inner in _CELL_ATTR_RE.findall(tr):
            while (r_index, col) in occupied:
                col += 1
            rowspan = _span(attrs, "rowspan")
            colspan = _span(attrs, "colspan")
            text = _TAG_RE.sub(" ", inner)
            text = html_lib.unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
            cells.append(
                {
                    "r": r_index,
                    "c": col,
                    "rs": rowspan,
                    "cs": colspan,
                    "text": text,
                }
            )
            for rr in range(r_index, r_index + rowspan):
                for cc in range(col, col + colspan):
                    occupied.add((rr, cc))
            col += colspan
        max_col = max(max_col, col)
    return cells, len(rows), max_col


def _span(attrs: str, name: str) -> int:
    match = re.search(rf"{name}\s*=\s*['\"]?(\d+)", attrs or "", re.I)
    if not match:
        return 1
    return max(1, int(match.group(1)))


def _scan_label_values(
    rule: dict,
    ctx: MatchContext,
    table_bbox,
    rows: list[list[str]],
    row_keywords: list[str],
    value_re,
    canvas: float,
    cw: float,
    ch: float,
) -> list[Box]:
    boxes: list[Box] = []
    positions = _positions(rule)
    x0, y0, _x1, _y1 = table_bbox
    seen: set[tuple[int, int]] = set()
    for r_i, values in enumerate(rows):
        for ci, text in enumerate(values):
            label = _norm(text)
            if not label or not any(keyword in label for keyword in row_keywords):
                continue
            for position in positions:
                target = _scan_target(rows, r_i, ci, position)
                if target is None or target in seen:
                    continue
                t_row, t_ci = target
                value = rows[t_row][t_ci].strip() if t_ci < len(rows[t_row]) else ""
                if not value or not value_re.search(value):
                    continue
                line_ctx = " ".join(rows[t_row])
                if whitelist_hit(value, line_ctx, rule, ctx.ruleset):
                    continue
                seen.add(target)
                cell_bbox = [
                    x0 + t_ci * cw,
                    y0 + t_row * ch,
                    x0 + (t_ci + 1) * cw,
                    y0 + (t_row + 1) * ch,
                ]
                rect = mineru_bbox_to_rect(ctx.page_rect, cell_bbox, canvas)
                boxes.append(
                    ctx.make_box(
                        rule,
                        rect,
                        value,
                        source="mineru",
                        confidence=min(float(rule.get("confidence", 0.8)), 0.65),
                        state="pending",
                        note=f"table_{position}_grid",
                    )
                )
                break
    return boxes


def _scan_target(rows: list[list[str]], row_i: int, col_i: int, position: str) -> tuple[int, int] | None:
    if position == "same":
        return row_i, col_i
    if position == "below":
        next_row = row_i + 1
        if next_row < len(rows) and col_i < len(rows[next_row]):
            return next_row, col_i
        return None
    for ci in range(col_i + 1, len(rows[row_i])):
        if rows[row_i][ci].strip():
            return row_i, ci
    return None


_TAG_RE = re.compile(r"<[^>]+>")
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_CELL_ATTR_RE = re.compile(r"<t[dh]([^>]*)>(.*?)</t[dh]>", re.S | re.I)


def _parse_html_table(html: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in _TR_RE.findall(html):
        cells = []
        for cell in _CELL_RE.findall(tr):
            text = _TAG_RE.sub(" ", cell)
            text = html_lib.unescape(text)
            cells.append(re.sub(r"\s+", " ", text).strip())
        if cells:
            rows.append(cells)
    return rows