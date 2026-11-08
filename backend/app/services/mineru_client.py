from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.services.pdf_split import PdfPart

_ERROR_MESSAGES = {
    "A0202": "MinerU Token 无效",
    "A0211": "MinerU Token 已过期",
    "-60005": "文件大小超过 MinerU 单文件限制（200MB）",
    "-60006": "页数超过 MinerU 单文件限制（200 页）",
    "-60009": "MinerU 队列已满，请稍后重试",
    "-60018": "MinerU 每日解析页数已达上限",
}
_RETRYABLE = {"-60009"}


class MineruError(RuntimeError):
    def __init__(self, message: str, *, code: str = "", retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class MineruCancelled(MineruError):
    pass


class OfficialMineruClient:
    """MinerU 官方精准解析 API v4 客户端。"""

    def __init__(
        self,
        token: str | None = None,
        base: str | None = None,
        timeout: float = 120.0,
        poll_interval: int | None = None,
        max_wait: int | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.token = (token if token is not None else settings.mineru_api_token).strip()
        if not self.token:
            raise MineruError("未配置 MINERU_API_TOKEN，无法调用 MinerU 官方解析")
        self.base = (base or settings.mineru_api_base).rstrip("/")
        self.poll_interval = poll_interval or settings.mineru_poll_interval
        self.max_wait = max_wait or settings.mineru_timeout
        self.client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=15.0),
            follow_redirects=True,
            headers={
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "bid-redact/0.2",
            },
            transport=transport,
        )
        self._plain = httpx.Client(
            timeout=httpx.Timeout(300.0, connect=15.0),
            follow_redirects=True,
            headers={"User-Agent": "bid-redact/0.2"},
            transport=transport,
        )

    def close(self) -> None:
        self.client.close()
        self._plain.close()

    def __enter__(self) -> "OfficialMineruClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def submit(self, parts: list[PdfPart]) -> str:
        if not parts:
            raise MineruError("没有可提交的 PDF 分片")
        files = []
        for part in parts:
            item = {
                "name": part.name,
                "data_id": part.data_id,
                "is_ocr": settings.mineru_is_ocr,
            }
            if part.page_range:
                item["page_ranges"] = part.page_range
            files.append(item)

        payload = {
            "files": files,
            "model_version": settings.mineru_model_version,
            "enable_table": settings.mineru_enable_table,
            "enable_formula": settings.mineru_enable_formula,
            "language": settings.mineru_language,
        }
        response = self.client.post(f"{self.base}/file-urls/batch", json=payload)
        data = self._unwrap(response)
        batch_id = data.get("batch_id")
        urls = data.get("file_urls") or data.get("upload_urls") or []
        if not batch_id:
            raise MineruError(f"MinerU 未返回 batch_id: {data}")
        if not isinstance(urls, list) or len(urls) != len(parts):
            raise MineruError(f"MinerU 返回的上传地址数量不匹配: {len(urls)} != {len(parts)}")

        for part, url in zip(parts, urls):
            self._upload(url, part.path)
        return str(batch_id)

    def _upload(self, url: str, path: Path) -> None:
        # 预签名 URL 的签名通常不包含 Content-Type；额外发送会导致
        # OSS SignatureDoesNotMatch，因此这里不要设置 Content-Type。
        response = self._plain.put(url, content=path.read_bytes())
        if response.status_code >= 400:
            raise MineruError(
                f"上传分片失败 HTTP {response.status_code}: {response.text[:300]}"
            )

    def wait(self, batch_id: str, expected: int, *, should_cancel=None, on_poll=None) -> list[dict]:
        deadline = time.monotonic() + self.max_wait
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            if should_cancel and should_cancel():
                raise MineruCancelled("任务已终止")
            response = self.client.get(f"{self.base}/extract-results/batch/{batch_id}")
            data = self._unwrap(response)
            last = data
            results = _extract_results(data)
            if on_poll:
                on_poll(results)
            done = [r for r in results if _state(r) in ("done", "success", "succeeded")]
            failed = [r for r in results if _state(r) in ("failed", "error")]
            if failed:
                item = failed[0]
                message = item.get("err_msg") or item.get("message") or "MinerU 解析失败"
                raise MineruError(f"{message}: {item}")
            if len(done) >= expected:
                return results
            time.sleep(self.poll_interval)
        raise MineruError(f"MinerU 解析超时（{self.max_wait}s），最后状态: {last}")

    def download_zip(self, url: str, dest: str | Path) -> Path:
        dest = Path(dest)
        response = self._plain.get(url)
        if response.status_code >= 400:
            raise MineruError(
                f"下载解析结果失败 HTTP {response.status_code}: {response.text[:300]}"
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(response.content)
        return dest

    def _unwrap(self, response: httpx.Response) -> dict:
        if response.status_code >= 400:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise MineruError(
                f"MinerU HTTP {response.status_code}: {response.text[:500]}",
                retryable=retryable,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MineruError(f"MinerU 返回非 JSON: {response.text[:300]}") from exc
        if not isinstance(payload, dict):
            raise MineruError(f"MinerU 返回结构异常: {payload}")
        code = payload.get("code")
        if code not in (None, 0, "0"):
            raise _api_error(code, payload.get("msg") or payload.get("message") or "")
        data = payload.get("data")
        return data if isinstance(data, dict) else payload


def _api_error(code, message: str) -> MineruError:
    key = str(code)
    friendly = _ERROR_MESSAGES.get(key, message or f"MinerU 返回错误码 {key}")
    return MineruError(
        f"{friendly}（code={key}）",
        code=key,
        retryable=key in _RETRYABLE,
    )


def _extract_results(data: dict) -> list[dict]:
    for key in ("extract_result", "extract_results", "results", "files"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _state(item: dict) -> str:
    return str(item.get("state") or item.get("status") or "").lower()


def result_for_part(results: list[dict], part: PdfPart) -> dict | None:
    for item in results:
        if str(item.get("data_id") or "") == part.data_id:
            return item
    for item in results:
        if str(item.get("file_name") or "") == part.name:
            return item
    return None


def zip_url(item: dict) -> str | None:
    for key in ("full_zip_url", "zip_url", "full_zip_url_list"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, list) and value:
            return str(value[0])
    return None