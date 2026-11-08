from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

import pymupdf

from app.core.config import settings
from app.rules.box import Box
from app.rules.normalize import clamp
from app.services.mineru_client import MineruCancelled

logger = logging.getLogger("bidredact.stamp")

PAGE_KEYWORDS = ("工程预算审核书", "预算审核书", "预算审核报告", "预算审核")

_H_MIN = 85
_H_MAX = 160
_S_MIN = 45
_V_MIN = 30
_MIN_AREA_RATIO = 0.0008
_MAX_AREA_RATIO = 0.15
_MIN_SIDE_PX = 30
_MIN_BLUE_RATIO = 0.02
_MIN_EXTENT = 0.12
_MIN_ASPECT = 0.35
_MAX_ASPECT = 2.8


def _page_text(page: pymupdf.Page, blocks: list[dict]) -> str:
    parts = [page.get_text("text")]
    for block in blocks:
        text = block.get("text") or block.get("table_body") or ""
        if text:
            parts.append(str(text))
    return "\n".join(parts)


def _digest() -> str:
    payload = {
        "version": 1,
        "dpi": settings.blue_stamp_dpi,
        "h": [_H_MIN, _H_MAX],
        "s": _S_MIN,
        "v": _V_MIN,
        "min_area": _MIN_AREA_RATIO,
        "min_blue": _MIN_BLUE_RATIO,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def detect_blue_stamps(
    source: str | Path,
    sha: str,
    blocks_by_page: dict[int, list[dict]] | None = None,
    *,
    should_cancel=None,
) -> tuple[list[Box], str]:
    if not settings.blue_stamp_enabled:
        return [], "disabled"

    blocks_by_page = blocks_by_page or {}
    source = Path(source)
    cache_file = settings.data_dir / "stamps" / "cache" / f"{sha}.{_digest()}.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return [_box_from_dict(item) for item in data.get("boxes", [])], "cache"
        except Exception:
            logger.warning("蓝色印章缓存损坏，重新检测: %s", cache_file, exc_info=True)
            cache_file.unlink(missing_ok=True)

    try:
        import cv2
        import numpy as np
    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenCV 不可用，跳过蓝色印章检测: %s", exc)
        return [], "unavailable"

    doc = pymupdf.open(source)
    boxes: list[Box] = []
    scanned = 0
    started = time.monotonic()
    try:
        dpi = max(72, settings.blue_stamp_dpi)
        for page_no, page in enumerate(doc):
            if should_cancel and should_cancel():
                raise MineruCancelled("任务已终止")
            if not any(
                keyword in _page_text(page, blocks_by_page.get(page_no, []))
                for keyword in PAGE_KEYWORDS
            ):
                continue
            scanned += 1
            try:
                found = _detect_page(page, page_no, dpi, cv2, np)
            except MineruCancelled:
                raise
            except Exception:
                logger.warning("第 %s 页蓝色印章检测失败", page_no + 1, exc_info=True)
                continue
            boxes.extend(found)
    finally:
        doc.close()

    logger.info(
        "蓝色印章检测完成: pages=%s boxes=%s elapsed=%.2fs",
        scanned,
        len(boxes),
        time.monotonic() - started,
    )
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
        logger.warning("写入蓝色印章缓存失败: %s", cache_file, exc_info=True)
    return boxes, "official"


def _detect_page(page: pymupdf.Page, page_no: int, dpi: int, cv2, np) -> list[Box]:
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    if pix.width < 64 or pix.height < 64:
        return []
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n
    )
    if image.shape[2] == 4:
        image = image[:, :, :3]
    bgr = image[:, :, ::-1].copy()
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.array([_H_MIN, _S_MIN, _V_MIN]),
        np.array([_H_MAX, 255, 255]),
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.dilate(
        mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=1
    )

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    height, width = mask.shape[:2]
    page_area = float(width * height)
    candidates: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        bbox_area = w * h
        if w < _MIN_SIDE_PX or h < _MIN_SIDE_PX:
            continue
        if bbox_area < page_area * _MIN_AREA_RATIO or bbox_area > page_area * _MAX_AREA_RATIO:
            continue
        aspect = w / h if h else 0
        if not _MIN_ASPECT <= aspect <= _MAX_ASPECT:
            continue
        extent = cv2.contourArea(contour) / bbox_area if bbox_area else 0
        if extent < _MIN_EXTENT:
            continue
        roi = mask[y : y + h, x : x + w]
        if (roi > 0).mean() < _MIN_BLUE_RATIO:
            continue
        candidates.append((x, y, w, h))

    merged = _merge(candidates)
    scale_x = page.rect.width / width
    scale_y = page.rect.height / height
    boxes: list[Box] = []
    for x, y, w, h in merged:
        rect = pymupdf.Rect(
            page.rect.x0 + x * scale_x,
            page.rect.y0 + y * scale_y,
            page.rect.x0 + (x + w) * scale_x,
            page.rect.y0 + (y + h) * scale_y,
        )
        rect = clamp(rect, page.rect)
        boxes.append(
            Box(
                page=page_no,
                rect=rect,
                category="secret",
                rule_id="BLUE-STAMP",
                mode="rect",
                source="opencv_blue_stamp",
                confidence=0.78,
                value="",
                state="redacted",
                note="blue_stamp",
            )
        )
    return boxes


def _merge(candidates: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    merged: list[list[int]] = []
    for x, y, w, h in candidates:
        rect = [x, y, x + w, y + h]
        for existing in merged:
            if _overlap_or_close(rect, existing):
                existing[0] = min(existing[0], rect[0])
                existing[1] = min(existing[1], rect[1])
                existing[2] = max(existing[2], rect[2])
                existing[3] = max(existing[3], rect[3])
                break
        else:
            merged.append(rect)
    return [(r[0], r[1], r[2] - r[0], r[3] - r[1]) for r in merged]


def _overlap_or_close(a: list[int], b: list[int], gap: int = 12) -> bool:
    return not (
        a[2] + gap < b[0]
        or b[2] + gap < a[0]
        or a[3] + gap < b[1]
        or b[3] + gap < a[1]
    )


def _box_dict(box: Box) -> dict:
    return {
        "page": box.page,
        "rect": [round(v, 2) for v in (box.rect.x0, box.rect.y0, box.rect.x1, box.rect.y1)],
    }


def _box_from_dict(item: dict) -> Box:
    rect = item["rect"]
    return Box(
        page=int(item["page"]),
        rect=pymupdf.Rect(float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])),
        category="secret",
        rule_id="BLUE-STAMP",
        mode="rect",
        source="opencv_blue_stamp",
        confidence=0.78,
        value="",
        state="redacted",
        note="blue_stamp",
    )