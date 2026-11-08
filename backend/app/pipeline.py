from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

import pymupdf

from app.core.config import settings
from app.redactor.redactor import redact_document
from app.rules.box import Box
from app.rules.dedupe import dedupe
from app.rules.engine import locate
from app.rules.loader import RuleSet, load_rules
from app.services.face_detector import FaceDetectorError, detect_faces
from app.services.mineru_client import (
    MineruCancelled,
    MineruError,
    OfficialMineruClient,
    result_for_part,
    zip_url,
)
from app.services.mineru_parse import group_by_page, normalize_bbox_spaces, parse_result_zip
from app.services.mineru_usage import release, reserve
from app.services.pdf_split import split_pdf
from app.services.pdf_type import classify_document
from app.services.social_insurance_detector import detect_social_insurance
from app.services.stamp_detector import detect_blue_stamps


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _replace_with_retry(src: Path, dest: Path) -> None:
    for attempt in range(10):
        try:
            os.replace(src, dest)
            return
        except PermissionError:
            if attempt >= 9:
                raise
            time.sleep(0.2)


def _cache_digest() -> str:
    raw = "|".join(
        [
            settings.mineru_model_version,
            str(settings.mineru_is_ocr),
            str(settings.mineru_enable_table),
            str(settings.mineru_enable_formula),
            settings.mineru_language,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


def mineru_blocks(
    source: Path,
    sha: str,
    page_sizes: list[tuple[float, float]],
    *,
    should_cancel=None,
    on_progress=None,
) -> tuple[dict[int, list[dict]], str, str]:
    cache_dir = settings.data_dir / "mineru" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{sha}.official-{_cache_digest()}.json"
    if cache_file.exists():
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        blocks = data.get("blocks") or []
        return group_by_page(blocks), "cache", data.get("bbox_space", "normalized")

    if not settings.mineru_api_token.strip():
        raise MineruError("未配置 MINERU_API_TOKEN，扫描/混合件无法调用 MinerU 官方解析")

    total_pages = len(page_sizes)
    reserve(total_pages, settings.mineru_max_daily_pages)
    temp_dir = (
        settings.data_dir
        / "mineru"
        / "tmp"
        / f"{sha[:16]}-{int(time.time() * 1000)}"
    )
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        parts = split_pdf(
            source,
            temp_dir,
            data_prefix=sha[:16],
            max_pages=settings.mineru_split_pages,
            max_mb=settings.mineru_split_mb,
        )
        blocks: list[dict] = []
        last_error: MineruError | None = None
        for attempt in range(3):
            if should_cancel and should_cancel():
                raise MineruCancelled("任务已终止")
            try:
                with OfficialMineruClient() as client:
                    batch_id = client.submit(parts)
                    results = client.wait(
                        batch_id,
                        len(parts),
                        should_cancel=should_cancel,
                        on_poll=on_progress,
                    )
                    blocks = []
                    for part in parts:
                        item = result_for_part(results, part)
                        url = zip_url(item) if item else None
                        if not url:
                            raise MineruError(f"分片 {part.name} 未返回 full_zip_url: {item}")
                        zip_path = client.download_zip(url, temp_dir / f"{part.data_id}.zip")
                        blocks.extend(
                            parse_result_zip(zip_path, page_offset=part.page_offset)
                        )
                last_error = None
                break
            except MineruCancelled:
                raise
            except MineruError as exc:
                last_error = exc
                if not exc.retryable or attempt >= 2:
                    raise
                time.sleep(5 * (attempt + 1))

        if last_error is not None:
            raise last_error
        if not blocks:
            raise MineruError("MinerU 未返回可解析的文本/表格/图片块")

        blocks, bbox_space = normalize_bbox_spaces(blocks, page_sizes)
        cache_file.write_text(
            json.dumps(
                {
                    "version": 2,
                    "provider": "official",
                    "bbox_space": bbox_space,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "blocks": blocks,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return group_by_page(blocks), "official", bbox_space
    except Exception:
        release(total_pages)
        raise
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def run(
    source: Path,
    output: Path,
    *,
    rules_path: Path | None = None,
    ruleset: RuleSet | None = None,
    mineru_mode: str = "auto",
    seal_guard: bool = True,
    report_path: Path | None = None,
    should_cancel=None,
    on_progress=None,
) -> dict:
    t0 = time.monotonic()
    if ruleset is None:
        if rules_path is None:
            raise ValueError("ruleset 与 rules_path 至少提供一个")
        ruleset = load_rules(rules_path)
    sha = file_sha256(source)

    doc = pymupdf.open(source)
    try:
        doc_type, page_types = classify_document(doc)
        page_sizes = [(page.rect.width, page.rect.height) for page in doc]
    finally:
        doc.close()

    warnings: list[str] = []
    blocks_by_page: dict[int, list[dict]] = {}
    mineru_state = "skipped"
    bbox_space = "unknown"
    scan_pages = [i + 1 for i, t in enumerate(page_types) if t == "scan"]

    if should_cancel and should_cancel():
        raise MineruCancelled("任务已终止")

    if (scan_pages or mineru_mode == "on") and mineru_mode != "off":
        blocks_by_page, mineru_state, bbox_space = mineru_blocks(
            source,
            sha,
            page_sizes,
            should_cancel=should_cancel,
        )
    elif scan_pages:
        warnings.append(f"存在扫描页但已关闭 MinerU: {scan_pages}")

    if should_cancel and should_cancel():
        raise MineruCancelled("任务已终止")

    face_boxes = []
    face_state = "disabled"
    face_model = ""
    face_scanned = 0
    face_elapsed = 0.0
    if settings.face_detection_enabled:
        try:
            face_result = detect_faces(
                source,
                sha,
                page_types,
                should_cancel=should_cancel,
                on_progress=on_progress,
            )
            face_boxes = face_result.boxes
            face_state = face_result.state
            face_model = face_result.model
            face_scanned = face_result.scanned_pages
            face_elapsed = face_result.elapsed_sec
        except FaceDetectorError as exc:
            if settings.face_fail_policy == "fail":
                raise
            face_state = "failed"
            warnings.append(f"人脸检测失败: {exc}")

    faces_by_page: dict[int, list[pymupdf.Rect]] = {}
    for face in face_boxes:
        faces_by_page.setdefault(face.page, []).append(face.rect)
    face_detection_active = settings.face_detection_enabled and face_state in (
        "official",
        "cache",
    )

    doc = pymupdf.open(source)
    try:
        located = locate(
            doc,
            ruleset,
            blocks_by_page,
            page_types,
            faces_by_page=faces_by_page,
            face_detection=face_detection_active,
        )
    finally:
        doc.close()

    # InsightFace 接管身份证头像：P5 只保留号码框。
    if face_detection_active and settings.face_replace_id_avatar:
        located.boxes = [
            box
            for box in located.boxes
            if not (box.rule_id == "RED-02" and "id_card_avatar" in (box.note or ""))
        ]
    if should_cancel and should_cancel():
        raise MineruCancelled("任务已终止")

    stamp_boxes: list[Box] = []
    stamp_state = "disabled"
    if settings.blue_stamp_enabled:
        stamp_boxes, stamp_state = detect_blue_stamps(
            source,
            sha,
            blocks_by_page,
            should_cancel=should_cancel,
        )

    ss_boxes: list[Box] = []
    ss_state = "disabled"
    if settings.social_insurance_enabled:
        ss_boxes, ss_state = detect_social_insurance(
            source,
            sha,
            blocks_by_page,
            should_cancel=should_cancel,
        )

    extras = face_boxes + stamp_boxes + ss_boxes
    if extras:
        located.boxes = dedupe(located.boxes + extras)

    if should_cancel and should_cancel():
        raise MineruCancelled("任务已终止")

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_output = output.parent / f"{output.stem}.tmp-{os.getpid()}-{threading.get_ident()}.pdf"
    try:
        result = redact_document(
            source, tmp_output, located.boxes, ruleset, apply_seal_guard=seal_guard
        )
        _replace_with_retry(tmp_output, output)
    finally:
        tmp_output.unlink(missing_ok=True)

    states: dict[str, int] = {}
    for box in located.boxes:
        states[box.state] = states.get(box.state, 0) + 1

    report = {
        "file": str(source),
        "sha256": sha,
        "pages": len(page_types),
        "doc_type": doc_type,
        "page_types": page_types,
        "rules_version": ruleset.version,
        "rules_sha256": ruleset.sha256,
        "mineru": mineru_state,
        "mineru_bbox_space": bbox_space,
        "face_detection": {
            "enabled": settings.face_detection_enabled,
            "state": face_state,
            "model": face_model,
            "scanned_pages": face_scanned,
            "faces": len(face_boxes),
            "elapsed_sec": face_elapsed,
        },
        "blue_stamp": {
            "enabled": settings.blue_stamp_enabled,
            "state": stamp_state,
            "boxes": len(stamp_boxes),
        },
        "social_insurance": {
            "enabled": settings.social_insurance_enabled,
            "state": ss_state,
            "boxes": len(ss_boxes),
        },
        "scan_pages": scan_pages,
        "warnings": warnings,
        "locate_errors": located.errors,
        "rule_stats": located.stats,
        "box_count": len(located.boxes),
        "box_states": states,
        "boxes": [b.to_dict() for b in located.boxes],
        "selfcheck": result.selfcheck,
        "attempts": result.attempts,
        "mosaic_tiles": result.mosaic_tiles,
        "redact_errors": result.errors,
        "output": str(output),
        "elapsed_sec": round(time.monotonic() - t0, 2),
    }

    if report_path is None:
        report_path = output.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report