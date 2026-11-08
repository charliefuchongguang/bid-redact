from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from app.redactor.mosaic import draw_mosaic
from app.redactor.seal_guard import red_ratio
from app.rules.box import Box
from app.rules.loader import RuleSet
from app.rules.normalize import clamp


@dataclass
class RedactResult:
    output_path: Path
    attempts: int = 0
    mosaic_tiles: int = 0
    selfcheck: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    page_boxes: dict[int, int] = field(default_factory=dict)


def redact_document(
    source: str | Path,
    output: str | Path,
    boxes: list[Box],
    ruleset: RuleSet,
    *,
    apply_seal_guard: bool = True,
) -> RedactResult:
    source = Path(source)
    output = Path(output)
    cfg = ruleset.global_cfg
    fill = _to_unit(cfg.get("fill", [0, 0, 0]))
    check_cfg = ruleset.selfcheck
    seal_cfg = ruleset.seal
    max_retry = int(check_cfg.get("max_retry", 3))
    expand = float(check_cfg.get("expand", 1.5))
    target = float(check_cfg.get("black_ratio", 0.98))
    threshold = int(check_cfg.get("black_threshold", 40))
    dpi = int(check_cfg.get("dpi", 150))

    result = RedactResult(output_path=output)
    active = [b for b in boxes if b.state != "skipped_seal"]

    if apply_seal_guard:
        _apply_seal_guard(source, active, ruleset)
        active = [b for b in active if b.state != "skipped_seal"]

    for attempt in range(1, max_retry + 1):
        result.attempts = attempt
        doc = pymupdf.open(source)
        try:
            pages = sorted({b.page for b in active})
            for page_no in pages:
                page = doc[page_no]
                page_boxes = [b for b in active if b.page == page_no]
                _remove_overlays(page, [b.rect for b in page_boxes])
                for box in page_boxes:
                    page.add_redact_annot(box.rect, fill=fill)

            graphics_mode = getattr(
                pymupdf, "PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED", 2
            )
            for page_no in pages:
                try:
                    doc[page_no].apply_redactions(
                        images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                        graphics=graphics_mode,
                    )
                except Exception as exc:
                    result.errors.append(f"apply_redactions p{page_no}: {type(exc).__name__}: {exc}")

            failed: list[Box] = []
            checks: list[dict] = []
            for box in active:
                page = doc[box.page]
                ratio = _black_ratio(page, box.rect, dpi, threshold)
                ok = ratio >= target
                checks.append(
                    {
                        "page": box.page,
                        "rule_id": box.rule_id,
                        "rect": [round(v, 2) for v in box.rect],
                        "black_ratio": round(ratio, 4),
                        "ok": ok,
                    }
                )
                if not ok:
                    failed.append(box)

            result.selfcheck = {
                "target": target,
                "attempt": attempt,
                "total": len(checks),
                "passed": len(checks) - len(failed),
                "failed": len(failed),
                "items": checks,
            }

            if failed and attempt < max_retry:
                for box in failed:
                    box.rect = _expand(box.rect, expand, doc[box.page].rect)
                continue

            if failed:
                for box in failed:
                    box.state = "pending"
                    box.note = f"{box.note}; selfcheck_failed" if box.note else "selfcheck_failed"

            mapping = ruleset.mosaic
            for box in active:
                page = doc[box.page]
                seed = f"{source.name}:{box.page}:{box.rule_id}:{box.rect}"
                result.mosaic_tiles += draw_mosaic(page, box.rect, mapping, seed)
            result.page_boxes = _count_by_page(active)
            doc.save(output, garbage=4, deflate=True, clean=True)
            return result
        finally:
            doc.close()

    return result


def _remove_overlays(page: pymupdf.Page, rects: list[pymupdf.Rect]) -> None:
    """删除与遮挡区重叠的印章/表单等 annotation，避免其盖在黑色填充之上。"""
    if not rects:
        return
    for annot in list(page.annots() or []):
        try:
            if annot.type[0] == pymupdf.PDF_ANNOT_REDACT:
                continue
            if any((annot.rect & rect).get_area() > 0 for rect in rects):
                page.delete_annot(annot)
        except Exception:
            continue
    for widget in list(page.widgets() or []):
        try:
            if any((widget.rect & rect).get_area() > 0 for rect in rects):
                page.delete_widget(widget)
        except Exception:
            continue


def _apply_seal_guard(source: Path, active: list[Box], ruleset: RuleSet) -> None:
    if not active:
        return
    cfg = ruleset.seal
    skip_ratio = float(cfg.get("red_ratio_skip", 0.10))
    doc = pymupdf.open(source)
    try:
        for box in active:
            rule = ruleset.rule(box.rule_id) or {}
            ratio = red_ratio(
                doc[box.page],
                box.rect,
                dpi=100,
                r_min=int(cfg.get("r_min", 150)),
                rg_min=int(cfg.get("rg_min", 50)),
                rb_min=int(cfg.get("rb_min", 50)),
            )
            box.note = f"{box.note}; red={ratio:.3f}" if box.note else f"red={ratio:.3f}"
            if rule.get("protect_seal") and ratio > skip_ratio:
                box.state = "skipped_seal"
    finally:
        doc.close()


def _black_ratio(page: pymupdf.Page, rect: pymupdf.Rect, dpi: int, threshold: int) -> float:
    clip = pymupdf.Rect(rect) & page.rect
    if clip.is_empty or clip.width < 0.5 or clip.height < 0.5:
        return 1.0
    pix = page.get_pixmap(dpi=dpi, clip=clip, colorspace=pymupdf.csRGB, alpha=False)
    samples = pix.samples
    stride = pix.n
    total = pix.width * pix.height
    if total <= 0:
        return 1.0
    black = 0
    for i in range(0, len(samples), stride):
        if samples[i] < threshold and samples[i + 1] < threshold and samples[i + 2] < threshold:
            black += 1
    return black / total


def _expand(rect: pymupdf.Rect, factor: float, page_rect: pymupdf.Rect) -> pymupdf.Rect:
    cx = (rect.x0 + rect.x1) / 2
    cy = (rect.y0 + rect.y1) / 2
    w = rect.width * factor / 2
    h = rect.height * factor / 2
    return clamp(pymupdf.Rect(cx - w, cy - h, cx + w, cy + h), page_rect)


def _to_unit(color) -> tuple[float, float, float]:
    values = tuple(float(v) for v in color[:3])
    if max(values) > 1.0:
        return tuple(v / 255.0 for v in values)
    return values


def _count_by_page(boxes: list[Box]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for box in boxes:
        counts[box.page] = counts.get(box.page, 0) + 1
    return counts