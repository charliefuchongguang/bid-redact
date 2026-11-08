from __future__ import annotations

from pathlib import Path

import pymupdf

from app.redactor.redactor import redact_document
from app.rules.box import Box
from app.rules.loader import load_rules

RULES = Path(__file__).resolve().parents[2] / "rules" / "rules.yaml"


def test_redact_removes_text_and_draws_mosaic(tmp_path):
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((50, 100), "SECRET-13800138000", fontsize=14)
    doc.save(src)
    doc.close()

    ruleset = load_rules(RULES)
    box = Box(0, pymupdf.Rect(45, 85, 220, 105), "personal", "RED-03", "rect", "text", 0.95, "13800138000")
    result = redact_document(src, out, [box], ruleset, apply_seal_guard=False)

    assert out.exists()
    assert result.selfcheck["passed"] == result.selfcheck["total"] == 1

    redacted = pymupdf.open(out)
    try:
        assert "SECRET" not in redacted[0].get_text()
        pix = redacted[0].get_pixmap(dpi=100, clip=pymupdf.Rect(45, 85, 220, 105), alpha=False)
        samples = pix.samples
        stride = pix.n
        values = [samples[i] for i in range(0, len(samples), stride)]
        assert max(values) <= 200
        assert min(values) >= 0
    finally:
        redacted.close()