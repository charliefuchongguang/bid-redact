r"""广东省建筑设计研究院集团股份有限公司案例回归验证（离线，不调用 MinerU API）。

使用 testdata 中用户提供的 PDF 和 MinerU 已解析 JSON，验证：
- 投标函报价不遮挡，其他报价继续遮挡；
- 社保证明只遮条码/验证码/证件号码，不遮参保人姓名/单位编号；
- 身份证背面整条底部遮挡；
- 工程预算审核书蓝色印章遮挡；
- 规则、人脸、蓝色印章、社保证明服务可以协同工作。

用法（在 backend 目录）：
    ..\.venv\Scripts\python.exe -m scripts.validate_case_gdadri
    ..\.venv\Scripts\python.exe -m scripts.validate_case_gdadri --pages 3 8 11 34 45 127
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pymupdf

from app.core.config import PROJECT_ROOT
from app.redactor.redactor import redact_document
from app.rules.box import Box
from app.rules.dedupe import dedupe
from app.rules.engine import locate
from app.rules.loader import load_rules
from app.rules.normalize import mineru_bbox_to_rect
from app.services.face_detector import detect_faces
from app.services.mineru_parse import extract_layout_blocks, group_by_page, normalize_bbox_spaces
from app.services.pdf_type import classify_document
from app.services.social_insurance_detector import detect_social_insurance
from app.services.stamp_detector import detect_blue_stamps

DEFAULT_PAGES = [3, 8, 11, 34, 45, 127]
PDF_NAME = "广东省建筑设计研究院集团股份有限公司-脱敏前.pdf"
MINERU_NAME = "MinerU_广东省建筑设计研究院集团股份有限公司-脱敏前__20261107012032.json"
RULES = PROJECT_ROOT / "rules" / "rules.yaml"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", nargs="*", type=int, default=DEFAULT_PAGES)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "validation" / "gdadri_subset_redacted.pdf",
    )
    args = parser.parse_args()

    testdata = PROJECT_ROOT / "testdata"
    pdf = testdata / PDF_NAME
    mineru = testdata / MINERU_NAME
    if not pdf.exists() or not mineru.exists():
        print(f"缺少案例文件: {pdf} 或 {mineru}", file=sys.stderr)
        return 2

    pages = sorted({p for p in args.pages if p >= 1})
    ruleset = load_rules(RULES)

    source = pymupdf.open(pdf)
    page_sizes = [(page.rect.width, page.rect.height) for page in source]
    _, page_types = classify_document(source)
    max_page = len(source)
    pages = [p for p in pages if p <= max_page]
    indices = [p - 1 for p in pages]

    data = json.loads(mineru.read_text(encoding="utf-8"))
    blocks, bbox_space = normalize_bbox_spaces(extract_layout_blocks(data), page_sizes)
    blocks_by_page = group_by_page(blocks)

    subset = PROJECT_ROOT / "data" / "validation" / "gdadri_subset_source.pdf"
    subset.parent.mkdir(parents=True, exist_ok=True)
    source.select(indices)
    source.save(subset)
    source.close()
    subset_sha = hashlib.sha256(subset.read_bytes()).hexdigest()

    doc = pymupdf.open(subset)
    try:
        subset_types = [page_types[i] for i in indices]
        subset_blocks = {new: blocks_by_page.get(old, []) for new, old in enumerate(indices)}
        faces = detect_faces(subset, subset_sha, subset_types)
        faces_by_page: dict[int, list[pymupdf.Rect]] = {}
        for face in faces.boxes:
            faces_by_page.setdefault(face.page, []).append(face.rect)

        located = locate(
            doc,
            ruleset,
            subset_blocks,
            subset_types,
            faces_by_page=faces_by_page,
            face_detection=faces.state in {"official", "cache"},
        )
        stamp_boxes, stamp_state = detect_blue_stamps(subset, subset_sha, subset_blocks)
        ss_boxes, ss_state = detect_social_insurance(subset, subset_sha, subset_blocks)
        all_boxes = dedupe(located.boxes + faces.boxes + stamp_boxes + ss_boxes)
    finally:
        doc.close()

    original_page = {new: old for new, old in enumerate(indices)}
    for box in all_boxes:
        box.page = original_page[box.page]

    by_page: dict[int, list[Box]] = {}
    for box in all_boxes:
        by_page.setdefault(box.page + 1, []).append(box)

    checks: list[tuple[str, bool, str]] = []
    _check_bid_letter(checks, by_page)
    _check_quote_table(checks, by_page)
    _check_social_insurance(checks, by_page, pdf, indices, blocks_by_page, page_sizes)
    _check_blue_stamp(checks, by_page)
    _check_id_back(checks, by_page, pdf, indices, blocks_by_page, page_sizes)
    _check_id_front(checks, by_page)

    print(f"rules={ruleset.version} pages={pages} bbox_space={bbox_space}")
    print(f"faces={faces.state}/{len(faces.boxes)} stamps={stamp_state}/{len(stamp_boxes)} social={ss_state}/{len(ss_boxes)}")
    for page_no in pages:
        items = by_page.get(page_no, [])
        print(f"  page {page_no}: {len(items)} boxes")
        for box in items:
            print(
                f"    {box.rule_id:10s} {box.note or '-':24s} "
                f"[{box.rect.x0:.1f},{box.rect.y0:.1f},{box.rect.x1:.1f},{box.rect.y1:.1f}]"
            )

    _write_output(args.output, pdf, indices, all_boxes, ruleset)

    failed = [item for item in checks if not item[1]]
    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    print(f"result={'PASS' if not failed else 'FAIL'} checks={len(checks)} failed={len(failed)}")
    return 0 if not failed else 1


def _check_bid_letter(checks, by_page) -> None:
    boxes = by_page.get(3, [])
    amount_rules = [b for b in boxes if b.rule_id in {"RED-10", "RED-21", "RED-23"}]
    checks.append(
        (
            "投标函报价不遮挡",
            not amount_rules,
            f"RED-10/21/23 boxes={len(amount_rules)}",
        )
    )


def _check_quote_table(checks, by_page) -> None:
    boxes = by_page.get(11, [])
    amount_boxes = [b for b in boxes if b.rule_id in {"RED-10", "RED-11", "RED-21", "RED-23"}]
    checks.append(
        (
            "其他报价继续遮挡",
            len(amount_boxes) >= 3,
            f"page 11 amount boxes={len(amount_boxes)}",
        )
    )


def _check_social_insurance(checks, by_page, pdf, indices, blocks_by_page, page_sizes) -> None:
    if 34 not in by_page:
        checks.append(("社保证明条码/验证码", False, "page 34 未选择"))
        return
    boxes = by_page.get(34, [])
    notes = {b.note for b in boxes if b.rule_id == "SS-CODE"}
    id_boxes = [b for b in boxes if b.rule_id in {"RED-01", "RED-28"}]
    checks.append(
        (
            "社保证明条码/验证码",
            "barcode" in notes and "verify_code" in notes,
            f"SS-CODE notes={sorted(notes)}",
        )
    )
    checks.append(
        (
            "社保证明证件号码",
            bool(id_boxes),
            f"ID boxes={[(b.rule_id, b.note) for b in id_boxes]}",
        )
    )

    page_rect = pymupdf.Rect(0, 0, *page_sizes[33])
    name_rect = _block_rect(blocks_by_page, 33, "参保人姓名", page_rect)
    unit_rect = _block_rect(blocks_by_page, 33, "单位编号", page_rect)
    name_hit = _overlapping(boxes, name_rect)
    unit_hit = _overlapping(boxes, unit_rect)
    checks.append(
        (
            "参保人姓名/单位编号保留",
            name_rect is not None and not name_hit and not unit_hit,
            f"name_hit={name_hit} unit_hit={unit_hit}",
        )
    )


def _check_blue_stamp(checks, by_page) -> None:
    boxes = [b for b in by_page.get(45, []) if b.rule_id == "BLUE-STAMP"]
    checks.append(("预算审核书蓝色印章", bool(boxes), f"BLUE-STAMP boxes={len(boxes)}"))


def _check_id_back(checks, by_page, pdf, indices, blocks_by_page, page_sizes) -> None:
    if 127 not in by_page:
        checks.append(("身份证背面底部遮挡", False, "page 127 未选择"))
        return
    boxes = [b for b in by_page.get(127, []) if b.rule_id == "RED-02"]
    back = [b for b in boxes if "id_card_back" in (b.note or "")]
    checks.append(("身份证背面底部遮挡", bool(back), f"back boxes={len(back)}"))

    page_rect = pymupdf.Rect(0, 0, *page_sizes[126])
    cert_rect = _block_rect(blocks_by_page, 126, "毕业证书", page_rect)
    cert_hit = _overlapping(boxes, cert_rect, threshold=0.05)
    checks.append(
        (
            "毕业证书照片不误判",
            cert_rect is not None and not cert_hit,
            f"cert_hit={cert_hit}",
        )
    )


def _check_id_front(checks, by_page) -> None:
    boxes = [b for b in by_page.get(127, []) if b.rule_id == "RED-02"]
    has_avatar = any("id_card_avatar" in (b.note or "") for b in boxes)
    has_number = any("id_card_number" in (b.note or "") for b in boxes)
    checks.append(
        (
            "身份证正面头像/号码",
            has_avatar and has_number,
            f"avatar={has_avatar} number={has_number}",
        )
    )


def _block_rect(blocks_by_page, page_idx: int, keyword: str, page_rect: pymupdf.Rect):
    for block in blocks_by_page.get(page_idx, []):
        text = block.get("text") or block.get("table_body") or ""
        bbox = block.get("bbox")
        if keyword in str(text) and bbox:
            return mineru_bbox_to_rect(page_rect, bbox, 1000.0)
    return None


def _overlapping(boxes: list[Box], rect: pymupdf.Rect | None, threshold: float = 0.10) -> bool:
    if rect is None or rect.is_empty:
        return False
    area = rect.get_area()
    if area <= 0:
        return False
    for box in boxes:
        inter = box.rect & rect
        if not inter.is_empty and inter.get_area() / area > threshold:
            return True
    return False


def _write_output(output: Path, pdf: Path, indices: list[int], boxes: list[Box], ruleset) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_source = output.parent / "gdadri_subset_source_tmp.pdf"
    source = pymupdf.open(pdf)
    try:
        source.select(indices)
        source.save(tmp_source)
    finally:
        source.close()

    page_map = {original: new for new, original in enumerate(indices)}
    subset_boxes: list[Box] = []
    for box in boxes:
        new_page = page_map.get(box.page)
        if new_page is None:
            continue
        subset_boxes.append(
            Box(
                page=new_page,
                rect=box.rect,
                category=box.category,
                rule_id=box.rule_id,
                mode=box.mode,
                source=box.source,
                confidence=box.confidence,
                value=box.value,
                state=box.state,
                note=box.note,
            )
        )
    result = redact_document(tmp_source, output, subset_boxes, ruleset)
    tmp_source.unlink(missing_ok=True)
    failed = [
        item for item in result.selfcheck.get("items", []) if not item.get("ok")
    ]
    print(f"output={output} selfcheck_failed={len(failed)}")
    for item in failed:
        print(
            f"  selfcheck page={item['page'] + 1} rule={item['rule_id']} "
            f"ratio={item['black_ratio']} rect={item['rect']}"
        )


if __name__ == "__main__":
    raise SystemExit(main())