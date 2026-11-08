from __future__ import annotations

import pymupdf


def red_ratio(
    page: pymupdf.Page,
    rect: pymupdf.Rect,
    *,
    dpi: int = 100,
    r_min: int = 150,
    rg_min: int = 50,
    rb_min: int = 50,
) -> float:
    clip = pymupdf.Rect(rect) & page.rect
    if clip.is_empty or clip.width < 1 or clip.height < 1:
        return 0.0
    pix = page.get_pixmap(dpi=dpi, clip=clip, colorspace=pymupdf.csRGB, alpha=False)
    samples = pix.samples
    stride = pix.n
    total = pix.width * pix.height
    if total <= 0:
        return 0.0
    red = 0
    for i in range(0, len(samples), stride):
        r = samples[i]
        g = samples[i + 1]
        b = samples[i + 2]
        if r > r_min and (r - g) > rg_min and (r - b) > rb_min:
            red += 1
    return red / total