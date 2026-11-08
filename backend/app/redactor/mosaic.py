from __future__ import annotations

import hashlib
import random

import pymupdf


def draw_mosaic(
    page: pymupdf.Page,
    rect: pymupdf.Rect,
    cfg: dict,
    seed: str,
    *,
    dpi_scale: float = 1.0,
) -> int:
    if not cfg.get("enabled", True):
        return 0
    area = pymupdf.Rect(rect) & page.rect
    if area.is_empty or area.width < 0.5 or area.height < 0.5:
        return 0

    tile = float(cfg.get("tile_pt", 6)) * dpi_scale
    if tile <= 0:
        tile = 6.0
    max_tiles = int(cfg.get("max_tiles", 4000))
    if cfg.get("adaptive", True) and max_tiles > 0:
        while (
            (area.width / tile + 1) * (area.height / tile + 1) > max_tiles
        ):
            tile *= 1.5

    palette = cfg.get("palette") or [[96, 96, 96]]
    rng = random.Random(hashlib.sha256(seed.encode("utf-8")).hexdigest())

    count = 0
    y = area.y0
    while y < area.y1 - 1e-6:
        y2 = min(y + tile, area.y1)
        x = area.x0
        while x < area.x1 - 1e-6:
            x2 = min(x + tile, area.x1)
            color = _to_unit(rng.choice(palette))
            page.draw_rect(
                pymupdf.Rect(x, y, x2, y2),
                color=None,
                fill=color,
                overlay=True,
            )
            count += 1
            x = x2
        y = y2
    return count


def _to_unit(color) -> tuple[float, float, float]:
    values = tuple(float(v) for v in color[:3])
    if max(values) > 1.0:
        return tuple(v / 255.0 for v in values)
    return values