from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf

from app.rules.box import Box
from app.rules.loader import RuleSet
from app.rules.normalize import clamp, pad_rect


@dataclass
class MatchContext:
    doc: pymupdf.Document
    page_no: int
    page: pymupdf.Page
    page_type: str
    ruleset: RuleSet
    blocks: list[dict] = field(default_factory=list)
    faces: list[pymupdf.Rect] = field(default_factory=list)
    face_detection: bool = False
    _text: str | None = None
    _dict: dict | None = None
    _combined: str | None = None

    @property
    def page_rect(self) -> pymupdf.Rect:
        return self.page.rect

    @property
    def text(self) -> str:
        if self._text is None:
            self._text = self.page.get_text("text")
        return self._text

    @property
    def combined_text(self) -> str:
        """PDF 文本层 + MinerU 文本层，供页面级关键词判断使用。"""
        if self._combined is None:
            parts = [self.text]
            for block in self.blocks:
                block_text = block.get("text") or block.get("table_body") or ""
                if block_text:
                    parts.append(str(block_text))
            self._combined = "\n".join(parts)
        return self._combined

    @property
    def text_dict(self) -> dict:
        if self._dict is None:
            self._dict = self.page.get_text("dict")
        return self._dict

    @property
    def config(self) -> dict:
        return self.ruleset.global_cfg

    def pad_for(self, rule: dict) -> float:
        if "pad" in rule:
            return float(rule["pad"])
        mode = (rule.get("redact") or {}).get("mode")
        name = rule.get("name") or ""
        if mode in ("card", "image"):
            return float(self.config.get("pad_image", 4))
        if mode == "cell":
            return float(self.config.get("pad_cell", 3))
        if any(k in name for k in ("金额", "报价", "保证金", "营业额")):
            return float(self.config.get("pad_amount", 12))
        return float(self.config.get("pad_default", 8))

    def make_box(
        self,
        rule: dict,
        rect: pymupdf.Rect,
        value: str,
        source: str,
        confidence: float | None = None,
        state: str = "redacted",
        note: str = "",
        mode: str | None = None,
    ) -> Box:
        box_mode = mode or (rule.get("redact") or {}).get("mode", "rect")
        rect = pad_rect(clamp(rect, self.page_rect), self.pad_for(rule), self.page_rect)
        return Box(
            page=self.page_no,
            rect=rect,
            category=rule.get("category", "unknown"),
            rule_id=rule["id"],
            mode=box_mode,
            source=source,
            confidence=float(rule.get("confidence", 0.8) if confidence is None else confidence),
            value=value,
            state=state,
            note=note,
        )


def iter_text_lines(ctx: MatchContext):
    """遍历文本层每一行的 (text, bbox)。"""
    for block in ctx.text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            if text.strip():
                yield text, list(line.get("bbox", (0, 0, 0, 0)))


def iter_mineru_blocks(ctx: MatchContext):
    for block in ctx.blocks:
        text = str(block.get("text") or "")
        if text.strip():
            yield block, text