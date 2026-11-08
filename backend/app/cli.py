from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.config import PROJECT_ROOT
from app.pipeline import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bid-redact",
        description="投标文件离线脱敏 CLI",
    )
    parser.add_argument("input", type=Path, help="输入 PDF")
    parser.add_argument("-o", "--output", type=Path, required=True, help="输出脱敏 PDF")
    parser.add_argument(
        "--rules",
        type=Path,
        default=PROJECT_ROOT / "rules" / "rules.yaml",
        help="规则库路径",
    )
    parser.add_argument(
        "--mineru",
        choices=("auto", "on", "off"),
        default="auto",
        help="auto=扫描页时调用；on=强制调用；off=关闭",
    )
    parser.add_argument("--no-seal-guard", action="store_true", help="关闭红章重叠跳过")
    parser.add_argument("--report", type=Path, default=None, help="报告 JSON 输出路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source: Path = args.input
    if not source.exists():
        print(f"输入文件不存在: {source}", file=sys.stderr)
        return 2
    if source.suffix.lower() != ".pdf":
        print("仅支持 PDF", file=sys.stderr)
        return 2

    report = run(
        source=source,
        output=args.output,
        rules_path=args.rules,
        mineru_mode=args.mineru,
        seal_guard=not args.no_seal_guard,
        report_path=args.report,
    )

    print(f"源文件    : {report['file']}")
    print(f"页数/类型 : {report['pages']} / {report['doc_type']}")
    print(f"规则版本  : {report['rules_version']}")
    print(f"Mineru    : {report['mineru']}")
    print(f"遮蔽框    : {report['box_count']}  状态={report['box_states']}")
    if report["rule_stats"]:
        print("命中规则  : " + ", ".join(f"{k}x{v}" for k, v in sorted(report["rule_stats"].items())))
    sc = report.get("selfcheck") or {}
    print(f"自检      : {sc.get('passed', 0)}/{sc.get('total', 0)} 通过（第 {sc.get('attempt', 0)} 次）")
    print(f"马赛克    : {report['mosaic_tiles']} 格")
    print(f"耗时      : {report['elapsed_sec']}s")
    if report["warnings"]:
        for w in report["warnings"]:
            print(f"警告      : {w}")
    if report["locate_errors"]:
        for e in report["locate_errors"][:5]:
            print(f"规则异常  : {e}")
    print(f"输出      : {report['output']}")
    print(f"报告      : {args.report or Path(args.output).with_suffix('.report.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())