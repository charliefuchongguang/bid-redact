r"""生成合成测试样本（文本页 + 表格 + 红章 + 扫描页）。

用法（在 backend 目录）：
    ..\.venv\Scripts\python.exe -m scripts.make_sample
"""
from __future__ import annotations

from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

from app.core.config import PROJECT_ROOT

OUT_DIR = PROJECT_ROOT / "testdata" / "_probe"
FONT = "china-s"


def text(page: pymupdf.Page, x: float, y: float, content: str, size: float = 12, color=(0, 0, 0)):
    page.insert_text((x, y), content, fontsize=size, fontname=FONT, color=color)


def page_bid_letter(doc: pymupdf.Document) -> pymupdf.Page:
    page = doc.new_page(width=595, height=842)
    text(page, 230, 80, "投 标 函", 20)
    text(page, 72, 130, "致：某某招标代理有限公司", 12)
    text(page, 72, 170, "公司名称：黑龙江示例建筑工程有限公司", 12)
    text(page, 72, 200, "统一社会信用代码：91230100MA1B12345X", 12)
    text(page, 72, 230, "法定代表人：张三", 12)
    text(page, 72, 270, "投标总价：¥1,292,072.30", 12)
    text(page, 72, 300, "（大写）：壹佰贰拾玖万贰仟零柒拾贰元叁角整", 12)
    text(page, 72, 340, "联系人：李四", 12)
    text(page, 72, 370, "手机：13800138000", 12)
    text(page, 72, 400, "电子邮箱：lisi@example.com", 12)
    text(page, 72, 430, "地址：北京市朝阳区某某路 1 号院 2 号楼", 12)
    return page


def card_image(path: Path) -> None:
    img = Image.new("RGB", (320, 202), (232, 232, 232))
    d = ImageDraw.Draw(img)
    d.rectangle((8, 8, 312, 194), outline=(120, 120, 120), width=2)
    d.ellipse((230, 20, 300, 90), fill=(200, 60, 60))
    img.save(path)


def page_basic_info(doc: pymupdf.Document, card_png: Path) -> pymupdf.Page:
    page = doc.new_page(width=595, height=842)
    text(page, 72, 80, "投标人基本情况表", 16)
    text(page, 72, 130, "账户名称：黑龙江示例建筑工程有限公司", 12)
    text(page, 72, 170, "银行账号：4111111111111111", 12)
    text(page, 72, 210, "开户行：中国银行哈尔滨某支行", 12)
    text(page, 72, 250, "基本存款账户编号：J3010125758402", 12)
    text(page, 72, 290, "电子邮箱：test@example.com", 12)

    page.insert_image(pymupdf.Rect(350, 330, 480, 412), filename=str(card_png))
    text(page, 356, 372, "11010519491231002X", 8)
    text(page, 72, 340, "法定代表人身份证号：11010519491231002X", 12)
    return page


def page_price_table(doc: pymupdf.Document) -> pymupdf.Page:
    page = doc.new_page(width=595, height=842)
    text(page, 72, 80, "分项报价表", 16)
    xs = [72, 120, 300, 400, 490]
    ys = [140, 172, 204, 236, 268]
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]), color=(0, 0, 0), width=1)
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y), color=(0, 0, 0), width=1)

    rows = [
        ["序号", "项目名称", "单价", "合价"],
        ["1", "设备 A", "89.70", "1,292,072.30"],
        ["2", "设备 B", "15.40", "123,456.78"],
        ["3", "服务费", "149.50", "50,000.00"],
    ]
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            text(page, xs[c] + 6, ys[r] + 20, value, 10)
    return page


def page_contract(doc: pymupdf.Document) -> pymupdf.Page:
    page = doc.new_page(width=595, height=842)
    text(page, 72, 80, "建设工程施工合同（节选）", 16)
    text(page, 72, 150, "合同金额：¥1,000,000.00", 12)
    # 红章覆盖金额右侧，用于验证 protect_seal 跳过
    page.draw_circle((450, 145), 45, color=(0.78, 0.12, 0.12), width=5)
    text(page, 372, 150, "壹佰万元整", 12)

    text(page, 72, 230, "合同保密条款：双方应对本合同内容保密，不得泄露。", 12)
    text(page, 72, 280, "投标总价（招标控制价）：¥1,500,000.00", 12)
    text(page, 72, 320, "招标控制价：¥1,500,000.00", 12)
    return page


def page_scan(doc: pymupdf.Document, source_index: int) -> pymupdf.Page:
    pix = doc[source_index].get_pixmap(dpi=200)
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, pixmap=pix)
    return page


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    card_png = OUT_DIR / "card.png"
    card_image(card_png)

    doc = pymupdf.open()
    page_bid_letter(doc)
    page_basic_info(doc, card_png)
    page_price_table(doc)
    page_contract(doc)

    text_only = OUT_DIR / "sample_text_only.pdf"
    doc.save(text_only, garbage=4, deflate=True)
    print(f"saved: {text_only} ({text_only.stat().st_size} bytes)")

    page_scan(doc, 0)
    text_scan = OUT_DIR / "sample_text_scan.pdf"
    doc.save(text_scan, garbage=4, deflate=True)
    doc.close()
    print(f"saved: {text_scan} ({text_scan.stat().st_size} bytes)")


if __name__ == "__main__":
    main()