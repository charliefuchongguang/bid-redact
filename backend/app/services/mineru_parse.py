from __future__ import annotations

import json
import zipfile
from pathlib import Path

IMAGE_TYPES = {"image", "figure", "img"}
TABLE_TYPES = {"table"}
TEXT_TYPES = {"text", "title", "list", "equation", "header", "footer", "page_number", "reference"}


def parse_result_zip(zip_path: str | Path, *, page_offset: int = 0) -> list[dict]:
    """从 MinerU full_zip 中读取 content_list.json / layout.json，返回统一 block 列表。

    block 统一结构：{"type": text|image|table, "text": str, "bbox": [x0,y0,x1,y1],
    "page_idx": int, "table_body": str|None}
    bbox 尚未归一化，由 normalize_bbox_spaces 统一处理。
    """
    zip_path = Path(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        content_name = _find_content_list(names)
        layout_name = _find_layout(names)

        if content_name:
            data = json.loads(zf.read(content_name).decode("utf-8"))
            blocks = extract_content_list(data)
            if blocks:
                return _apply_offset(blocks, page_offset)

        if layout_name:
            data = json.loads(zf.read(layout_name).decode("utf-8"))
            blocks = extract_layout_blocks(data)
            if blocks:
                return _apply_offset(blocks, page_offset)
    return []


def _find_content_list(names: list[str]) -> str | None:
    for name in names:
        base = name.rsplit("/", 1)[-1].lower()
        if base.endswith("_content_list.json") or base == "content_list.json":
            return name
    return None


def _find_layout(names: list[str]) -> str | None:
    for name in names:
        base = name.rsplit("/", 1)[-1].lower()
        if base in ("layout.json", "middle.json"):
            return name
    for name in names:
        base = name.rsplit("/", 1)[-1].lower()
        if base.endswith("_middle.json") or base.endswith("_layout.json"):
            return name
    return None


def extract_content_list(data) -> list[dict]:
    if isinstance(data, list):
        return [_from_content_block(item) for item in data if _valid_block(item)]
    if isinstance(data, dict):
        for key in ("content_list", "contentList", "blocks"):
            value = data.get(key)
            if isinstance(value, list):
                return [_from_content_block(item) for item in value if _valid_block(item)]
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except ValueError:
                    continue
                found = extract_content_list(parsed)
                if found:
                    return found
        for value in data.values():
            found = extract_content_list(value)
            if found:
                return found
    return []


def _valid_block(item) -> bool:
    return isinstance(item, dict) and isinstance(item.get("bbox"), (list, tuple))


def _bbox(item) -> list[float] | None:
    bbox = item.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        try:
            return [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
        except (TypeError, ValueError):
            return None
    poly = item.get("poly")
    if isinstance(poly, (list, tuple)) and len(poly) >= 4:
        try:
            xs = [float(poly[i]) for i in range(0, len(poly), 2)]
            ys = [float(poly[i]) for i in range(1, len(poly), 2)]
            return [min(xs), min(ys), max(xs), max(ys)]
        except (TypeError, ValueError, IndexError):
            return None
    return None


def _from_content_block(item: dict) -> dict:
    raw_type = str(item.get("type") or "text").lower()
    btype = _map_type(raw_type)
    text = item.get("text")
    if text is None:
        text = item.get("content")
    if text is None and isinstance(item.get("image_caption"), list):
        text = " ".join(str(v) for v in item["image_caption"])
    table_body = item.get("table_body") or item.get("html")
    return {
        "type": btype,
        "text": str(text or ""),
        "bbox": _bbox(item),
        "page_idx": _page_idx(item),
        "table_body": table_body,
    }


def extract_layout_blocks(data) -> list[dict]:
    if isinstance(data, dict) and isinstance(data.get("pdf_info"), list):
        blocks: list[dict] = []
        for page_no, page in enumerate(data["pdf_info"]):
            page_idx = int(page.get("page_idx", page_no))
            for block in page.get("preproc_blocks") or page.get("layout_dets") or []:
                converted = _from_layout_block(block, page_idx)
                if converted:
                    blocks.append(converted)
        return blocks

    if isinstance(data, dict) and isinstance(data.get("layout_dets"), list):
        return [
            converted
            for block in data["layout_dets"]
            if (converted := _from_layout_block(block, 0))
        ]

    if isinstance(data, list):
        if data and isinstance(data[0], dict) and "layout_dets" in data[0]:
            blocks = []
            for page_no, page in enumerate(data):
                page_idx = int(page.get("page_idx", page_no))
                for block in page.get("layout_dets") or []:
                    converted = _from_layout_block(block, page_idx)
                    if converted:
                        blocks.append(converted)
            return blocks
        return extract_content_list(data)
    return []


def _from_layout_block(block: dict, page_idx: int) -> dict | None:
    if not isinstance(block, dict):
        return None
    bbox = _bbox(block)
    if not bbox:
        return None
    raw_type = block.get("type")
    if raw_type is None:
        raw_type = _category_type(block.get("category_id"))
    raw_type = str(raw_type).lower()
    btype = _map_type(raw_type)
    text = _layout_text(block)
    table_body = block.get("table_body") or block.get("html")
    return {
        "type": btype,
        "text": text,
        "bbox": bbox,
        "page_idx": int(block.get("page_idx", page_idx)),
        "table_body": table_body,
    }


def _layout_text(block: dict) -> str:
    if block.get("text"):
        return str(block["text"])
    parts: list[str] = []
    for line in block.get("lines") or []:
        if not isinstance(line, dict):
            continue
        line_text = line.get("text")
        if line_text:
            parts.append(str(line_text))
            continue
        for span in line.get("spans") or []:
            if isinstance(span, dict) and span.get("content"):
                parts.append(str(span["content"]))
    if parts:
        return "".join(parts)
    for child in block.get("blocks") or []:
        if isinstance(child, dict):
            text = _layout_text(child)
            if text:
                parts.append(text)
    return "".join(parts)


def _category_type(value) -> str:
    try:
        category = int(value)
    except (TypeError, ValueError):
        return "text"
    if category in (2,):
        return "image"
    if category in (3,):
        return "table"
    return "text"


def _map_type(raw: str) -> str:
    if raw in IMAGE_TYPES:
        return "image"
    if raw in TABLE_TYPES:
        return "table"
    if raw in TEXT_TYPES:
        return "text"
    return "text"


def _page_idx(item: dict) -> int:
    try:
        return int(item.get("page_idx", 0))
    except (TypeError, ValueError):
        return 0


def _apply_offset(blocks: list[dict], offset: int) -> list[dict]:
    if offset:
        for block in blocks:
            block["page_idx"] = int(block.get("page_idx", 0)) + offset
    return blocks


def normalize_bbox_spaces(blocks: list[dict], page_sizes: list[tuple[float, float]], canvas: float = 1000.0) -> tuple[list[dict], str]:
    """自动判断 bbox 是页面 point 还是 0~canvas 归一化，并统一转为 0~canvas。"""
    valid = [b for b in blocks if isinstance(b.get("bbox"), list) and len(b["bbox"]) == 4]
    if not valid or not page_sizes:
        return blocks, "unknown"

    max_x = max(float(b["bbox"][2]) for b in valid)
    max_y = max(float(b["bbox"][3]) for b in valid)
    max_w = max(float(size[0]) for size in page_sizes)
    max_h = max(float(size[1]) for size in page_sizes)

    space = "point" if max_x <= max_w * 1.05 and max_y <= max_h * 1.05 else "normalized"
    if space == "normalized":
        return blocks, space

    for block in valid:
        page_idx = int(block.get("page_idx", 0))
        if page_idx < 0 or page_idx >= len(page_sizes):
            continue
        width, height = page_sizes[page_idx]
        if width <= 0 or height <= 0:
            continue
        x0, y0, x1, y1 = (float(v) for v in block["bbox"])
        block["bbox"] = [
            _clamp(x0 * canvas / width, 0, canvas),
            _clamp(y0 * canvas / height, 0, canvas),
            _clamp(x1 * canvas / width, 0, canvas),
            _clamp(y1 * canvas / height, 0, canvas),
        ]
    return blocks, space


def _clamp(value: float, low: float, high: float) -> float:
    return round(min(max(value, low), high), 2)


def group_by_page(blocks: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for block in blocks:
        try:
            page_no = int(block.get("page_idx", 0))
        except (TypeError, ValueError):
            page_no = 0
        grouped.setdefault(page_no, []).append(block)
    return grouped