from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

import pymupdf

from app.core.config import settings
from app.rules.box import Box
from app.rules.matchers.base import iter_text_lines
from app.rules.normalize import clamp, mineru_bbox_to_rect, pad_rect
from app.services.mineru_client import MineruCancelled

logger = logging.getLogger("bidredact.social")

PAGE_KEYWORDS = (
    "社会保险参保证明",
    "社保证明",
    "参保证明",
    "参保缴费证明",
    "参保缴费",
)
VERIFY_RE = re.compile(r"(验证码|校验码|查询码|防伪码)\s*[：:]?\s*([A-Za-z0-9]{4,})")
MIN_BARCODE_WIDTH = 25.0
MIN_BARCODE_ASPECT = 3.0
MAX_BARCODE_HEIGHT = 40.0


def _page_text(page: pymupdf.Page, blocks: list[dict]) -> str:
    parts = [page.get_text("text")]
    for block in blocks:
        text = block.get("text") or block.get("table_body") or ""
        if text:
            parts.append(str(text))
    return "\n".join(parts)


def _digest() -> str:
    raw = json.dumps(
        {
            "version": 2,
            "dpi": settings.social_insurance_dpi,
            "verify_fallback_x": 0.22,
            "verify_fallback_y": 0.03,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def detect_social_insurance(
    source: str | Path,
    sha: str,
    blocks_by_page: dict[int, list[dict]] | None = None,
    *,
    should_cancel=None,
) -> tuple[list[Box], str]:
    if not settings.social_insurance_enabled:
        return [], "disabled"

    blocks_by_page = blocks_by_page or {}
    source = Path(source)
    cache_file = (
        settings.data_dir / "social" / "cache" / f"{sha}.{_digest()}.json"
    )
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return [_box_from_dict(item) for item in data.get("boxes", [])], "cache"
        except Exception:
            logger.warning("社保证明缓存损坏，重新检测: %s", cache_file, exc_info=True)
            cache_file.unlink(missing_ok=True)

    doc = pymupdf.open(source)
    boxes: list[Box] = []
    scanned = 0
    try:
        for page_no, page in enumerate(doc):
            if should_cancel and should_cancel():
                raise MineruCancelled("任务已终止")
            blocks = blocks_by_page.get(page_no, [])
            page_text = _page_text(page, blocks)
            if not any(keyword in page_text for keyword in PAGE_KEYWORDS):
                continue
            scanned += 1
            try:
                boxes.extend(_detect_page(page, page_no, blocks))
            except MineruCancelled:
                raise
            except Exception:
                logger.warning("第 %s 页社保证明检测失败", page_no + 1, exc_info=True)
    finally:
        doc.close()

    try:
        cache_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "scanned_pages": scanned,
                    "boxes": [_box_dict(box) for box in boxes],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        logger.warning("写入社保证明缓存失败: %s", cache_file, exc_info=True)
    return boxes, "official"


def _detect_page(page: pymupdf.Page, page_no: int, blocks: list[dict]) -> list[Box]:
    canvas = 1000.0
    items = _text_items(page, blocks, canvas)
    barcode = _find_barcode(page, blocks, canvas)
    verify = _find_verify_code(items)

    boxes: list[Box] = []
    if barcode is not None:
        if verify is None:
            fallback = _verify_fallback_region(page, barcode)
            boxes.append(_make_box(page_no, fallback, "verify_code_fallback"))
        else:
            rect = pad_rect(clamp(barcode, page.rect), 2.0, page.rect)
            boxes.append(_make_box(page_no, rect, "barcode"))
    if verify is not None:
        rect = pad_rect(clamp(verify, page.rect), 2.0, page.rect)
        boxes.append(_make_box(page_no, rect, "verify_code"))
    return boxes


def _verify_fallback_region(page: pymupdf.Page, barcode: pymupdf.Rect) -> pymupdf.Rect:
    """OCR 漏识别验证码时，覆盖条形码及其右侧/下方验证码区域。"""
    page_rect = page.rect
    fallback = pymupdf.Rect(
        barcode.x0 - 3,
        barcode.y0 - 4,
        barcode.x1 + page_rect.width * 0.22,
        barcode.y1 + page_rect.height * 0.03,
    )
    return pad_rect(clamp(fallback, page_rect), 2.0, page_rect)


def _text_items(
    page: pymupdf.Page, blocks: list[dict], canvas: float
) -> list[tuple[str, pymupdf.Rect]]:
    items: list[tuple[str, pymupdf.Rect]] = []
    for text, bbox in iter_text_lines(
        _SimpleContext(page, blocks, canvas)
    ):
        if text.strip():
            items.append((text, pymupdf.Rect(bbox)))
    for block in blocks:
        text = str(block.get("text") or "")
        bbox = block.get("bbox")
        if not text.strip() or not bbox:
            continue
        items.append((text, mineru_bbox_to_rect(page.rect, bbox, canvas)))
    return items


class _SimpleContext:
    def __init__(self, page: pymupdf.Page, blocks: list[dict], canvas: float) -> None:
        self.page = page
        self.blocks = blocks
        self._dict = None
        self.config = {"mineru_canvas": canvas}

    @property
    def text_dict(self) -> dict:
        if self._dict is None:
            self._dict = self.page.get_text("dict")
        return self._dict


def _find_verify_code(items: list[tuple[str, pymupdf.Rect]]) -> pymupdf.Rect | None:
    for text, rect in items:
        if not VERIFY_RE.search(text):
            continue
        return rect
    return None


def _find_barcode(
    page: pymupdf.Page, blocks: list[dict], canvas: float
) -> pymupdf.Rect | None:
    candidates: list[pymupdf.Rect] = []
    for block in blocks:
        if block.get("type") != "image" or not block.get("bbox"):
            continue
        rect = mineru_bbox_to_rect(page.rect, block["bbox"], canvas)
        if _barcode_like(rect):
            candidates.append(rect)
    for rect in candidates:
        refined = _refine_with_opencv(page, rect)
        if refined is not None:
            return refined
    if candidates:
        return min(candidates, key=lambda r: r.get_area())
    return None


def _barcode_like(rect: pymupdf.Rect) -> bool:
    if rect.is_empty or rect.width < MIN_BARCODE_WIDTH:
        return False
    if rect.height <= 0 or rect.height > MAX_BARCODE_HEIGHT:
        return False
    return rect.width / rect.height >= MIN_BARCODE_ASPECT


def _refine_with_opencv(page: pymupdf.Page, rect: pymupdf.Rect) -> pymupdf.Rect | None:
    try:
        import cv2
        import numpy as np
    except Exception:
        return None
    clip = pad_rect(rect, 8.0, page.rect)
    try:
        pix = page.get_pixmap(
            dpi=max(200, settings.social_insurance_dpi),
            clip=clip,
            colorspace=pymupdf.csRGB,
            alpha=False,
        )
    except Exception:
        return None
    if pix.width < 16 or pix.height < 8:
        return None
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n
    )
    if image.shape[2] == 4:
        image = image[:, :, :3]
    bgr = image[:, :, ::-1].copy()
    try:
        found, points = cv2.barcode.BarcodeDetector().detect(bgr)
    except Exception:
        return None
    if not found or points is None:
        return None
    pts = np.asarray(points).reshape(-1, 2)
    if len(pts) < 4:
        return None
    sx = clip.width / pix.width
    sy = clip.height / pix.height
    return pymupdf.Rect(
        clip.x0 + float(pts[:, 0].min()) * sx,
        clip.y0 + float(pts[:, 1].min()) * sy,
        clip.x0 + float(pts[:, 0].max()) * sx,
        clip.y0 + float(pts[:, 1].max()) * sy,
    )


def _make_box(page_no: int, rect: pymupdf.Rect, note: str) -> Box:
    return Box(
        page=page_no,
        rect=rect,
        category="secret",
        rule_id="SS-CODE",
        mode="rect",
        source="ss_detector",
        confidence=0.95 if note == "barcode" else 0.92,
        value="",
        state="redacted",
        note=note,
    )


def _box_dict(box: Box) -> dict:
    return {
        "page": box.page,
        "rect": [round(v, 2) for v in (box.rect.x0, box.rect.y0, box.rect.x1, box.rect.y1)],
        "note": box.note,
    }


def _box_from_dict(item: dict) -> Box:
    rect = item["rect"]
    note = item.get("note", "")
    return Box(
        page=int(item["page"]),
        rect=pymupdf.Rect(float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])),
        category="secret",
        rule_id="SS-CODE",
        mode="rect",
        source="ss_detector",
        confidence=0.95 if note == "barcode" else 0.92,
        value="",
        state="redacted",
        note=note,
    )