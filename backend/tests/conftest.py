from __future__ import annotations

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def disable_face_detection_by_default(monkeypatch):
    monkeypatch.setattr(settings, "face_detection_enabled", False)