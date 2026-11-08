from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.core.config import settings
from app.rules.box import Box
from app.services import face_detector

RULES = Path(__file__).resolve().parents[2] / "rules" / "rules.yaml"


class FakeModel:
    def __init__(self, box=(0.4, 0.4, 0.6, 0.6), score=0.9):
        self.box = box
        self.score = score

    def detect(self, image, max_num=0):
        import numpy as np

        height, width = image.shape[:2]
        x0, y0, x1, y1 = self.box
        return (
            np.array(
                [[width * x0, height * y0, width * x1, height * y1, self.score]],
                dtype=np.float32,
            ),
            None,
        )


def _image_page_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "image.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 60), 0)
    pix.set_rect(pix.irect, (220, 220, 220))
    page.insert_image(pymupdf.Rect(50, 50, 350, 550), pixmap=pix)
    text_page = doc.new_page(width=400, height=600)
    text_page.insert_text((50, 80), "text only", fontsize=12)
    doc.save(path)
    doc.close()
    return path


def test_page_with_image_detected(tmp_path):
    path = _image_page_pdf(tmp_path)
    doc = pymupdf.open(path)
    try:
        assert face_detector._page_has_images(doc[0], "text")
        assert not face_detector._page_has_images(doc[1], "text")
        assert face_detector._page_has_images(doc[1], "scan")
    finally:
        doc.close()


def test_detect_page_maps_pixels_to_points(tmp_path):
    path = _image_page_pdf(tmp_path)
    doc = pymupdf.open(path)
    try:
        boxes = face_detector._detect_page(doc[0], 0, FakeModel())
    finally:
        doc.close()
    assert len(boxes) == 1
    box = boxes[0]
    assert box.page == 0
    assert box.rect.x0 == pytest.approx(150.4, abs=2.0)
    assert box.rect.width > 0
    assert box.rule_id == "FACE-01"


def test_detect_faces_skips_text_pages_and_caches(tmp_path, monkeypatch):
    path = _image_page_pdf(tmp_path)
    model_file = tmp_path / "det.onnx"
    model_file.write_bytes(b"fake")
    monkeypatch.setattr(settings, "face_detection_enabled", True)
    monkeypatch.setattr(settings, "face_scan_mode", "image_pages")
    monkeypatch.setattr(settings, "face_model_path", model_file)
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(face_detector, "_load_model", lambda *args, **kwargs: FakeModel())
    settings.ensure_dirs()

    result = face_detector.detect_faces(path, "sha-test", ["text", "text"])
    assert result.state == "official"
    assert result.scanned_pages == 1
    assert len(result.boxes) == 1

    cached = face_detector.detect_faces(path, "sha-test", ["text", "text"])
    assert cached.state == "cache"
    assert len(cached.boxes) == 1


