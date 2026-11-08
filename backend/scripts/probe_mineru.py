r"""MinerU 官方 API 连通性探针。

用法（在 backend 目录）：
    ..\.venv\Scripts\python.exe -m scripts.probe_mineru [PDF路径]

未传 PDF 时使用 testdata/_probe/sample_text_scan.pdf；需在 .env 配置 MINERU_API_TOKEN。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

from app.core.config import PROJECT_ROOT, settings
from app.pipeline import file_sha256, mineru_blocks


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        PROJECT_ROOT / "testdata" / "_probe" / "sample_text_scan.pdf"
    )
    if not source.exists():
        raise SystemExit(f"文件不存在: {source}")
    if not settings.mineru_api_token:
        raise SystemExit("未配置 MINERU_API_TOKEN")

    doc = pymupdf.open(source)
    try:
        page_sizes = [(page.rect.width, page.rect.height) for page in doc]
    finally:
        doc.close()

    blocks, state, bbox_space = mineru_blocks(source, file_sha256(source), page_sizes)
    count = sum(len(items) for items in blocks.values())
    print(f"file={source}")
    print(f"pages={len(page_sizes)} state={state} bbox_space={bbox_space} blocks={count}")
    for page_no in sorted(blocks)[:3]:
        print(f"  page {page_no + 1}: {len(blocks[page_no])} blocks")
        for block in blocks[page_no][:5]:
            print(f"    {block.get('type')} bbox={block.get('bbox')} text={str(block.get('text'))[:60]!r}")


if __name__ == "__main__":
    main()