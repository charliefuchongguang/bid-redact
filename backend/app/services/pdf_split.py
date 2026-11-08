from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass
class PdfPart:
    path: Path
    page_offset: int
    page_count: int
    page_range: str
    data_id: str = ""
    temporary: bool = False

    @property
    def name(self) -> str:
        return self.path.name


def needs_split(source: Path, total_pages: int, *, max_pages: int, max_mb: int) -> bool:
    return total_pages > max_pages or source.stat().st_size > max_mb * 1024 * 1024


def split_pdf(
    source: str | Path,
    out_dir: str | Path,
    *,
    data_prefix: str,
    max_pages: int = 200,
    max_mb: int = 200,
) -> list[PdfPart]:
    source = Path(source)
    out_dir = Path(out_dir)
    doc = pymupdf.open(source)
    try:
        total_pages = len(doc)
        if not needs_split(source, total_pages, max_pages=max_pages, max_mb=max_mb):
            return [
                PdfPart(
                    path=source,
                    page_offset=0,
                    page_count=total_pages,
                    page_range=f"1-{total_pages}",
                    data_id=f"{data_prefix}-1",
                )
            ]

        out_dir.mkdir(parents=True, exist_ok=True)
        parts = _split_range(
            doc,
            source,
            0,
            total_pages - 1,
            out_dir,
            data_prefix,
            max_pages=max_pages,
            max_bytes=max_mb * 1024 * 1024,
        )
        for index, part in enumerate(parts, start=1):
            part.data_id = f"{data_prefix}-{index}"
        return parts
    finally:
        doc.close()


def _split_range(
    doc: pymupdf.Document,
    source: Path,
    start: int,
    end: int,
    out_dir: Path,
    data_prefix: str,
    *,
    max_pages: int,
    max_bytes: int,
) -> list[PdfPart]:
    if end - start + 1 > max_pages:
        first_end = start + max_pages - 1
        return _split_range(
            doc, source, start, first_end, out_dir, data_prefix,
            max_pages=max_pages, max_bytes=max_bytes,
        ) + _split_range(
            doc, source, first_end + 1, end, out_dir, data_prefix,
            max_pages=max_pages, max_bytes=max_bytes,
        )

    part_path = out_dir / f"{data_prefix}-{start + 1}-{end + 1}.pdf"
    new_doc = pymupdf.open()
    try:
        new_doc.insert_pdf(doc, from_page=start, to_page=end)
        new_doc.save(part_path, garbage=4, deflate=True)
    finally:
        new_doc.close()

    if part_path.stat().st_size > max_bytes and end > start:
        part_path.unlink(missing_ok=True)
        mid = (start + end) // 2
        return _split_range(
            doc, source, start, mid, out_dir, data_prefix,
            max_pages=max_pages, max_bytes=max_bytes,
        ) + _split_range(
            doc, source, mid + 1, end, out_dir, data_prefix,
            max_pages=max_pages, max_bytes=max_bytes,
        )

    pages = end - start + 1
    return [
        PdfPart(
            path=part_path,
            page_offset=start,
            page_count=pages,
            page_range=f"1-{pages}",
            temporary=True,
        )
    ]