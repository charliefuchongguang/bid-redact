from __future__ import annotations

import pymupdf

from app.rules.box import Box
from app.rules.dedupe import dedupe


def _box(x0, y0, x1, y1, mode="rect", conf=0.9):
    return Box(0, pymupdf.Rect(x0, y0, x1, y1), "personal", "RED-X", mode, "text", conf, "v")


def test_dedupe_merges_high_iou():
    a = _box(0, 0, 100, 10)
    b = _box(1, 0, 101, 10)
    out = dedupe([a, b])
    assert len(out) == 1


def test_dedupe_merges_containment():
    outer = _box(0, 0, 200, 50, mode="card")
    inner = _box(10, 10, 100, 20)
    out = dedupe([outer, inner])
    assert len(out) == 1
    assert out[0].rect.x0 == 0 and out[0].rect.x1 == 200


def test_dedupe_keeps_separate_boxes():
    a = _box(0, 0, 100, 10)
    b = _box(0, 100, 100, 110)
    assert len(dedupe([a, b])) == 2