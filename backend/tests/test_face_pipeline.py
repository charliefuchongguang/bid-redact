from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app import pipeline as pipeline_module
from app.core.config import settings
from app.rules.box import Box
from app.rules.loader import load_rules
from app.services.face_detector import FaceDetectionResult, FaceDetectorError

RULES = Path(__file__).resolve().parents[2] / "rules" / "rules.yaml"


def _pdf(tmp_path: Path) -> Path:
    path = tmp_path / "doc.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "联系电话：13800138000", fontsize=14)
    doc.save(path)
    doc.close()
    return path


def test_pipeline_adds_face_box_and_report(tmp_path, monkeypatch):
    source = _pdf(tmp_path)
    face = Box(
        page=0,
        rect=pymupdf.Rect(100, 150, 160, 220),
        category="personal",
        rule_id="FACE-01",
        mode="rect",
        source="insightface",
        confidence=0.9,
        note="insightface_face",
    )
    monkeypatch.setattr(settings, "face_detection_enabled", True)
    monkeypatch.setattr(settings, "face_replace_id_avatar", True)
    monkeypatch.setattr(
        pipeline_module,
        "detect_faces",
        lambda *args, **kwargs: FaceDetectionResult(
            boxes=[face], state="official", model="det.onnx", scanned_pages=1, faces=1
        ),
    )
    out = tmp_path / "out.pdf"
    report = pipeline_module.run(
        source=source,
        output=out,
        ruleset=load_rules(RULES),
        mineru_mode="off",
    )
    assert any(box["rule_id"] == "FACE-01" for box in report["boxes"])
    assert report["face_detection"]["state"] == "official"
    assert report["face_detection"]["faces"] == 1
    assert out.exists()


def test_pipeline_face_failure_fails_task(tmp_path, monkeypatch):
    source = _pdf(tmp_path)
    monkeypatch.setattr(settings, "face_detection_enabled", True)
    monkeypatch.setattr(settings, "face_fail_policy", "fail")

    def fail(*args, **kwargs):
        raise FaceDetectorError("model missing")

    monkeypatch.setattr(pipeline_module, "detect_faces", fail)
    with pytest.raises(FaceDetectorError):
        pipeline_module.run(
            source=source,
            output=tmp_path / "out.pdf",
            ruleset=load_rules(RULES),
            mineru_mode="off",
        )