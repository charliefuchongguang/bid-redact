from __future__ import annotations

import hashlib

import pymupdf


def value_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Box:
    """一个待遮蔽区域（坐标单位：PDF point，page 为 0 基）。"""

    __slots__ = (
        "page",
        "rect",
        "category",
        "rule_id",
        "mode",
        "source",
        "confidence",
        "value",
        "state",
        "note",
    )

    def __init__(
        self,
        page: int,
        rect: pymupdf.Rect,
        category: str,
        rule_id: str,
        mode: str,
        source: str,
        confidence: float,
        value: str = "",
        state: str = "redacted",
        note: str = "",
    ) -> None:
        self.page = page
        self.rect = pymupdf.Rect(rect)
        self.category = category
        self.rule_id = rule_id
        self.mode = mode
        self.source = source
        self.confidence = confidence
        self.value = value
        self.state = state
        self.note = note

    @property
    def value_hash(self) -> str | None:
        return value_hash(self.value) if self.value else None

    def iou(self, other: "Box") -> float:
        if self.page != other.page:
            return 0.0
        inter = pymupdf.Rect(self.rect) & other.rect
        if inter.is_empty:
            return 0.0
        inter_area = inter.width * inter.height
        union = self.rect.width * self.rect.height + other.rect.width * other.rect.height - inter_area
        return inter_area / union if union > 0 else 0.0

    def containment(self, other: "Box") -> float:
        if self.page != other.page:
            return 0.0
        inter = pymupdf.Rect(self.rect) & other.rect
        if inter.is_empty:
            return 0.0
        inter_area = inter.width * inter.height
        smaller = min(self.rect.get_area(), other.rect.get_area())
        return inter_area / smaller if smaller > 0 else 0.0

    def union(self, other: "Box") -> None:
        self.rect = self.rect | other.rect

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "rect": [round(v, 2) for v in (self.rect.x0, self.rect.y0, self.rect.x1, self.rect.y1)],
            "category": self.category,
            "rule_id": self.rule_id,
            "mode": self.mode,
            "source": self.source,
            "confidence": round(self.confidence, 3),
            "state": self.state,
            "note": self.note,
            "value_hash": self.value_hash,
        }

    def __repr__(self) -> str:
        return (
            f"Box(p{self.page} {self.rule_id} {self.mode} "
            f"[{self.rect.x0:.1f},{self.rect.y0:.1f},{self.rect.x1:.1f},{self.rect.y1:.1f}])"
        )