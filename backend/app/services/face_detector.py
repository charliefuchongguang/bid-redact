from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pymupdf

from app.core.config import PROJECT_ROOT, settings
from app.rules.box import Box
from app.services.mineru_client import MineruCancelled

logger = logging.getLogger("bidredact.face")


class FaceDetectorError(RuntimeError):
    pass


@dataclass
class FaceDetectionResult:
    boxes: list[Box] = field(default_factory=list)
    state: str = "disabled"
    model: str = ""
    scanned_pages: int = 0
    faces: int = 0
    elapsed_sec: float = 0.0


_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: dict[tuple[str, int, int, float], object] = {}
_MODEL_SHA_CACHE: dict[str, str] = {}


def resolve_model_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _model_sha256(path: Path) -> str:
    key = str(path)
    cached = _MODEL_SHA_CACHE.get(key)
    if cached:
        return cached
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    _MODEL_SHA_CACHE[key] = value
    return value


def _load_model(model_path: Path, ctx_id: int, det_size: int, det_thresh: float):
    key = (str(model_path), ctx_id, det_size, det_thresh)
    with _MODEL_LOCK:
        if key in _MODEL_CACHE:
            return _MODEL_CACHE[key]

    if not model_path.exists():
        raise FaceDetectorError(
            f"人脸检测模型不存在: {model_path}；请运行 scripts.download_face_model 或挂载模型文件"
        )

    try:
        from insightface.model_zoo import get_model
    except Exception as exc:  # noqa: BLE001
        raise FaceDetectorError(
            "InsightFace 未安装或依赖不完整，请安装 requirements-face.txt"
        ) from exc

    kwargs = {}
    if settings.face_ort_threads > 0:
        try:
            import onnxruntime as ort

            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = settings.face_ort_threads
            sess_options.inter_op_num_threads = 1
            kwargs["sess_options"] = sess_options
        except Exception:
            logger.warning("设置 onnxruntime 线程数失败，使用默认值", exc_info=True)

    try:
        model = get_model(str(model_path), **kwargs)
        if model is None:
            raise FaceDetectorError(f"无法识别人脸检测模型: {model_path}")
        model.prepare(
            ctx_id=ctx_id,
            input_size=(det_size, det_size),
            det_thresh=det_thresh,
        )
    except FaceDetectorError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise FaceDetectorError(
            f"人脸检测模型加载失败: {type(exc).__name__}: {exc}"
        ) from exc

    with _MODEL_LOCK:
        _MODEL_CACHE[key] = model
    return model


def _page_has_images(page: pymupdf.Page, page_type: str) -> bool:
    if page_type == "scan":
        return True
    try:
        if page.get_images(full=True):
            return True
    except Exception:
        pass
    try:
        return bool(page.get_image_info(xrefs=True))
    except Exception:
        return True


def _config_digest(
    *,
    model_path: Path,
    model_sha: str,
    page_indices: list[int],
    page_count: int,
) -> str:
    payload = {
        "version": 1,
        "model": str(model_path.name),
        "model_sha256": model_sha,
        "dpi": settings.face_detect_dpi,
        "det_size": settings.face_det_size,
        "det_thresh": settings.face_det_thresh,
        "min_size": settings.face_min_size_pt,
        "pad_ratio": settings.face_pad_ratio,
        "tile_size": settings.face_tile_size,
        "scan_mode": settings.face_scan_mode,
        "page_count": page_count,
        "page_indices": page_indices,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _box_dict(box: Box) -> dict:
    return {
        "page": box.page,
        "rect": [round(v, 2) for v in (box.rect.x0, box.rect.y0, box.rect.x1, box.rect.y1)],
        "score": round(box.confidence, 4),
    }


def _box_from_dict(item: dict) -> Box:
    rect = item["rect"]
    return Box(
        page=int(item["page"]),
        rect=pymupdf.Rect(float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])),
        category="personal",
        rule_id="FACE-01",
        mode="rect",
        source="insightface",
        confidence=float(item.get("score", 0.0)),
        value="",
        state="redacted",
        note="insightface_face",
    )


def _iou(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    inter = a & b
    if inter.is_empty:
        return 0.0
    inter_area = inter.width * inter.height
    union = a.width * a.height + b.width * b.height - inter_area
    return inter_area / union if union > 0 else 0.0


def _detect_page(page: pymupdf.Page, page_no: int, model) -> list[Box]:
    import numpy as np

    dpi = max(36, settings.face_detect_dpi)
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    if pix.width < 8 or pix.height < 8:
        return []
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n
    )
    if image.shape[2] == 4:
        image = image[:, :, :3]
    if image.shape[2] == 1:
        image = np.repeat(image, 3, axis=2)
    image = image[:, :, ::-1].copy()

    detections: list[tuple[pymupdf.Rect, float]] = []
    tile_size = int(settings.face_tile_size or 0)
    if tile_size >= 256:
        height, width = image.shape[:2]
        overlap = max(32, int(tile_size * 0.15))
        step = max(64, tile_size - overlap)
        for y0 in range(0, height, step):
            y1 = min(y0 + tile_size, height)
            if y1 - y0 < 64:
                break
            for x0 in range(0, width, step):
                x1 = min(x0 + tile_size, width)
                if x1 - x0 < 64:
                    break
                tile = image[y0:y1, x0:x1]
                tile_boxes, _ = model.detect(tile, max_num=0)
                for row in tile_boxes:
                    bx0, by0, bx1, by1, score = (float(v) for v in row[:5])
                    detections.append(
                        (
                            pymupdf.Rect(bx0 + x0, by0 + y0, bx1 + x0, by1 + y0),
                            score,
                        )
                    )
                if x1 >= width:
                    break
            if y1 >= height:
                break
    else:
        bboxes, _ = model.detect(image, max_num=0)
        for row in bboxes:
            x0, y0, x1, y1, score = (float(v) for v in row[:5])
            detections.append((pymupdf.Rect(x0, y0, x1, y1), score))

    boxes: list[Box] = []
    page_rect = page.rect
    scale_x = page_rect.width / pix.width
    scale_y = page_rect.height / pix.height
    min_size = float(settings.face_min_size_pt)
    pad_ratio = max(0.0, float(settings.face_pad_ratio))
    kept: list[tuple[pymupdf.Rect, float]] = []

    for pixel_rect, score in sorted(detections, key=lambda item: item[1], reverse=True):
        if score < settings.face_det_thresh:
            continue
        if any(_iou(pixel_rect, other) >= 0.45 for other, _ in kept):
            continue
        rect = pymupdf.Rect(
            page_rect.x0 + pixel_rect.x0 * scale_x,
            page_rect.y0 + pixel_rect.y0 * scale_y,
            page_rect.x0 + pixel_rect.x1 * scale_x,
            page_rect.y0 + pixel_rect.y1 * scale_y,
        )
        rect = rect & page_rect
        if rect.is_empty or rect.width < min_size or rect.height < min_size:
            continue
        kept.append((pixel_rect, score))
        pad_x = rect.width * pad_ratio
        pad_y = rect.height * pad_ratio
        rect = pymupdf.Rect(
            max(page_rect.x0, rect.x0 - pad_x),
            max(page_rect.y0, rect.y0 - pad_y),
            min(page_rect.x1, rect.x1 + pad_x),
            min(page_rect.y1, rect.y1 + pad_y),
        )
        boxes.append(
            Box(
                page=page_no,
                rect=rect,
                category="personal",
                rule_id="FACE-01",
                mode="rect",
                source="insightface",
                confidence=score,
                value="",
                state="redacted",
                note="insightface_face",
            )
        )
    return boxes


def detect_faces(
    source: str | Path,
    sha: str,
    page_types: list[str] | None = None,
    *,
    should_cancel=None,
    on_progress=None,
) -> FaceDetectionResult:
    started = time.monotonic()
    if not settings.face_detection_enabled:
        return FaceDetectionResult(state="disabled")

    source = Path(source)
    page_types = page_types or []
    model_path = resolve_model_path(settings.face_model_path)
    result = FaceDetectionResult(state="skipped", model=model_path.name)

    doc = pymupdf.open(source)
    try:
        page_count = len(doc)
        page_indices: list[int] = []
        for index, page in enumerate(doc):
            if should_cancel and should_cancel():
                raise MineruCancelled("任务已终止")
            page_type = page_types[index] if index < len(page_types) else "text"
            if settings.face_scan_mode == "all" or _page_has_images(page, page_type):
                page_indices.append(index)

        if not page_indices:
            result.elapsed_sec = round(time.monotonic() - started, 2)
            return result

        if not model_path.exists():
            raise FaceDetectorError(
                f"人脸检测模型不存在: {model_path}；请运行 scripts.download_face_model 或挂载模型文件"
            )
        model_sha = _model_sha256(model_path)
        digest = _config_digest(
            model_path=model_path,
            model_sha=model_sha,
            page_indices=page_indices,
            page_count=page_count,
        )
        cache_dir = settings.data_dir / "faces" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{sha}.{digest}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                boxes = [_box_from_dict(item) for item in data.get("boxes", [])]
                result.boxes = boxes
                result.state = "cache"
                result.scanned_pages = int(data.get("scanned_pages", len(page_indices)))
                result.faces = len(boxes)
                result.elapsed_sec = round(time.monotonic() - started, 2)
                return result
            except Exception:
                logger.warning("人脸缓存损坏，重新检测: %s", cache_file, exc_info=True)
                cache_file.unlink(missing_ok=True)

        model = _load_model(
            model_path,
            settings.face_ctx_id,
            settings.face_det_size,
            settings.face_det_thresh,
        )
        boxes: list[Box] = []
        total = len(page_indices)
        if on_progress:
            on_progress(0, total)
        for done, index in enumerate(page_indices, start=1):
            if should_cancel and should_cancel():
                raise MineruCancelled("任务已终止")
            try:
                boxes.extend(_detect_page(doc[index], index, model))
            except MineruCancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                raise FaceDetectorError(
                    f"第 {index + 1} 页人脸检测失败: {type(exc).__name__}: {exc}"
                ) from exc
            if on_progress:
                on_progress(done, total)

        result.boxes = boxes
        result.state = "official"
        result.scanned_pages = total
        result.faces = len(boxes)
        result.elapsed_sec = round(time.monotonic() - started, 2)

        try:
            cache_file.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "model": model_path.name,
                        "model_sha256": model_sha,
                        "scanned_pages": total,
                        "faces": len(boxes),
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                        "boxes": [_box_dict(box) for box in boxes],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception:
            logger.warning("写入人脸缓存失败: %s", cache_file, exc_info=True)
        return result
    finally:
        doc.close()