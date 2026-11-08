r"""下载 InsightFace 官方模型包，只提取人脸检测 ONNX。

用法（在 backend 目录）：
    ..\.venv\Scripts\python.exe -m scripts.download_face_model --accept-license

默认提取 buffalo_l 中的 det_10g.onnx 到 data/models/insightface/。
如只需轻量模型，可改用：
    ..\.venv\Scripts\python.exe -m scripts.download_face_model --pack buffalo_sc --accept-license

注意：InsightFace 官方预训练模型默认仅限非商业研究用途；本脚本仅用于已取得授权的环境。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

import requests

from app.core.config import PROJECT_ROOT

PACKS = {
    "buffalo_l": {
        "url": "https://github.com/deepinsight/insightface/releases/download/model-zoo/buffalo_l.zip",
        "sha256": "80ffe37d8a5940d59a7384c201a2a38d4741f2f3c51eef46ebb28218a7b0ca2f",
        "model": "det_10g.onnx",
    },
    "buffalo_sc": {
        "url": "https://github.com/deepinsight/insightface/releases/download/model-zoo/buffalo_sc.zip",
        "sha256": "57d31b56b6ffa911c8a73cfc1707c73cab76efe7f13b675a05223bf42de47c72",
        "model": "det_500m.onnx",
    },
}

# GitHub Release 直连在部分网络下会被重置；镜像仅作传输，下载后用 SHA256 校验。
MIRRORS = (
    "https://ghfast.top/",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for candidate in (url, *(mirror + url for mirror in MIRRORS)):
        try:
            print(f"尝试下载: {candidate}")
            with requests.get(candidate, stream=True, timeout=(20, 300)) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length") or 0)
                done = 0
                with dest.open("wb") as fh:
                    for chunk in response.iter_content(1024 * 1024):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        done += len(chunk)
                        if total:
                            print(
                                f"\r下载 {done / 1024 / 1024:.1f}/{total / 1024 / 1024:.1f} MB",
                                end="",
                            )
            print()
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"\n下载失败: {type(exc).__name__}: {exc}", file=sys.stderr)
            dest.unlink(missing_ok=True)
    raise RuntimeError(f"所有下载地址均失败: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", choices=sorted(PACKS), default="buffalo_l")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "models" / "insightface")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--accept-license", action="store_true")
    args = parser.parse_args()

    if not args.accept_license:
        print("请确认已取得 InsightFace 预训练模型授权，并追加 --accept-license", file=sys.stderr)
        return 2

    pack = PACKS[args.pack]
    model_name = pack["model"]
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    target = output / model_name
    if target.exists() and not args.force:
        print(f"已存在: {target} ({target.stat().st_size} bytes)")
        return 0

    zip_path = output / "_download" / f"{args.pack}.zip"
    if not zip_path.exists() or args.force:
        print(f"下载 {args.pack}: {pack['url']}")
        _download(pack["url"], zip_path)
    actual = _sha256(zip_path)
    if actual != pack["sha256"]:
        print(f"校验失败: {actual} != {pack['sha256']}", file=sys.stderr)
        return 3

    with zipfile.ZipFile(zip_path) as zf:
        names = {Path(name).name: name for name in zf.namelist()}
        member = names.get(model_name)
        if not member:
            print(f"压缩包中未找到 {model_name}; 包含: {sorted(names)[:20]}", file=sys.stderr)
            return 4
        with zf.open(member) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)

    model_sha = _sha256(target)
    meta = {
        "pack": args.pack,
        "model": model_name,
        "model_sha256": model_sha,
        "model_size": target.stat().st_size,
        "pack_sha256": pack["sha256"],
        "source": pack["url"],
        "license": "InsightFace pretrained models: authorized use only",
    }
    (output / f"{model_name}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    zip_path.unlink(missing_ok=True)
    print(f"已保存: {target} ({target.stat().st_size} bytes)")
    print(f"sha256: {model_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())