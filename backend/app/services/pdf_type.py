from __future__ import annotations

import re

import pymupdf


def page_text_chars(page: pymupdf.Page) -> int:
    return len(re.sub(r"\s", "", page.get_text("text")))


def classify_page(page: pymupdf.Page, min_chars: int = 20) -> str:
    return "text" if page_text_chars(page) >= min_chars else "scan"


def classify_document(doc: pymupdf.Document, min_chars: int = 20) -> tuple[str, list[str]]:
    kinds = [classify_page(page, min_chars) for page in doc]
    if all(k == "text" for k in kinds):
        return "text", kinds
    if all(k == "scan" for k in kinds):
        return "scan", kinds
    return "mixed", kinds