from __future__ import annotations

from app.rules.box import Box

_MODE_PRIORITY = {"card": 4, "image": 3, "cell": 2, "rect": 1}


def dedupe(boxes: list[Box], iou_threshold: float = 0.7) -> list[Box]:
    ordered = sorted(
        boxes,
        key=lambda b: (b.page, -b.confidence, -_MODE_PRIORITY.get(b.mode, 0), -b.rect.get_area()),
    )
    kept: list[Box] = []
    for box in ordered:
        if box.rect.is_empty or box.rect.width < 0.5 or box.rect.height < 0.5:
            continue
        merged = False
        for existing in kept:
            if box.iou(existing) >= iou_threshold or box.containment(existing) >= 0.9:
                existing.union(box)
                if box.confidence > existing.confidence:
                    existing.confidence = box.confidence
                if _MODE_PRIORITY.get(box.mode, 0) > _MODE_PRIORITY.get(existing.mode, 0):
                    existing.mode = box.mode
                merged = True
                break
        if not merged:
            kept.append(box)
    return sorted(kept, key=lambda b: (b.page, b.rect.y0, b.rect.x0))