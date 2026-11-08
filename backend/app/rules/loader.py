from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

MATCH_TYPES = {"regex", "semantic", "table", "image"}
REDACT_MODES = {"rect", "card", "image", "cell"}
CATEGORY_KEYS = ("personal", "secret", "contact")


class RuleError(ValueError):
    pass


@dataclass
class RuleSet:
    version: str
    global_cfg: dict
    whitelist: list[dict]
    rules: list[dict]
    source_path: Path
    sha256: str
    description: str = ""
    _by_id: dict[str, dict] = field(default_factory=dict)

    def rule(self, rule_id: str) -> dict | None:
        return self._by_id.get(rule_id)

    def enabled_rules(self) -> list[dict]:
        return [r for r in self.rules if r.get("enabled", True)]

    @property
    def mosaic(self) -> dict:
        return self.global_cfg.get("mosaic", {})

    @property
    def selfcheck(self) -> dict:
        return self.global_cfg.get("selfcheck", {})

    @property
    def seal(self) -> dict:
        return self.global_cfg.get("seal", {})


def canonical_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_sha256(data: dict) -> str:
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def load_rules(path: str | Path) -> RuleSet:
    path = Path(path)
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    return ruleset_from_dict(
        data,
        source_path=path,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def load_rules_text(text: str, *, source_path: str | Path = "<text>") -> RuleSet:
    data = parse_rules_text(text)
    return ruleset_from_dict(data, source_path=source_path)


def parse_rules_text(text: str) -> dict:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RuleError(f"YAML 解析失败: {exc}") from exc
    if not isinstance(data, dict):
        raise RuleError("规则根节点必须是对象")
    return data


def ruleset_from_dict(
    data: dict,
    *,
    source_path: str | Path | None = None,
    sha256: str | None = None,
) -> RuleSet:
    errors = validate_rules_dict(data)
    if errors:
        raise RuleError("; ".join(errors[:5]))

    version = str(data.get("version") or "unknown")
    description = str(data.get("description") or "")
    global_cfg = data.get("global") or {}
    whitelist = [dict(item) for item in (data.get("whitelist") or [])]
    rules: list[dict] = []
    for category in CATEGORY_KEYS:
        for item in data.get(category) or []:
            rule = dict(item)
            rule.setdefault("category", category)
            rule["enabled"] = bool(rule.get("enabled", True))
            _normalize_on(rule)
            rules.append(rule)

    source = Path(source_path) if source_path is not None else Path("<memory>")
    digest = sha256 or payload_sha256(data)
    rs = RuleSet(
        version=version,
        global_cfg=dict(global_cfg),
        whitelist=whitelist,
        rules=rules,
        source_path=source,
        sha256=digest,
        description=description,
    )
    rs._by_id = {r["id"]: r for r in rules}
    return rs


def validate_rules_dict(data: dict) -> list[str]:
    if not isinstance(data, dict):
        return ["规则根节点必须是对象"]

    errors: list[str] = []
    version = data.get("version")
    if not version:
        errors.append("缺少 version")

    global_cfg = data.get("global")
    if global_cfg is not None and not isinstance(global_cfg, dict):
        errors.append("global 必须是对象")

    whitelist = data.get("whitelist")
    if whitelist is None:
        whitelist = []
    if not isinstance(whitelist, list):
        return errors + ["whitelist 必须是数组"]

    seen: set[str] = set()
    whitelist_ids: set[str] = set()
    for item in whitelist:
        if not isinstance(item, dict):
            errors.append(f"白名单项必须是对象: {item!r}")
            continue
        wid = item.get("id")
        if not wid:
            errors.append(f"白名单缺少 id: {item!r}")
            continue
        if wid in seen:
            errors.append(f"规则 id 重复: {wid}")
        seen.add(wid)
        whitelist_ids.add(wid)
        kind = item.get("type", "value")
        if kind not in ("value", "context"):
            errors.append(f"{wid}: 不支持的 whitelist.type={kind!r}")
        pattern = item.get("pattern")
        if pattern:
            try:
                re.compile(pattern)
            except re.error as exc:
                errors.append(f"{wid}: pattern 正则非法: {exc}")

    for category in CATEGORY_KEYS:
        items = data.get(category)
        if items is None:
            continue
        if not isinstance(items, list):
            errors.append(f"{category} 必须是数组")
            continue
        for item in items:
            if not isinstance(item, dict):
                errors.append(f"{category} 规则项必须是对象: {item!r}")
                continue
            rid = item.get("id")
            if not rid:
                errors.append(f"{category} 规则缺少 id: {item!r}")
                continue
            if rid in seen:
                errors.append(f"规则 id 重复: {rid}")
            seen.add(rid)
            try:
                rule = dict(item)
                rule.setdefault("category", category)
                _normalize_on(rule)
                _validate_rule(rule)
            except RuleError as exc:
                errors.append(str(exc))
                continue
            confidence = rule.get("confidence", 0.8)
            if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
                errors.append(f"{rid}: confidence 必须在 0~1")
            match = rule.get("match") or {}
            refs = match.get("whitelist") or []
            if not isinstance(refs, list):
                errors.append(f"{rid}: match.whitelist 必须是数组")
            else:
                for ref in refs:
                    if ref not in whitelist_ids:
                        errors.append(f"{rid}: 引用了不存在的白名单 {ref}")
    return errors


def _normalize_on(rule: dict) -> None:
    match = rule.get("match")
    if not isinstance(match, dict):
        return
    # YAML 1.1 会把裸键 on 解析成布尔 True，这里做一次归一化
    if True in match and "on" not in match:
        match["on"] = match.pop(True)


def _validate_unique(whitelist: list[dict], rules: list[dict]) -> None:
    seen: set[str] = set()
    for item in list(whitelist) + list(rules):
        rid = item.get("id")
        if not rid:
            raise RuleError(f"规则缺少 id: {item}")
        if rid in seen:
            raise RuleError(f"规则 id 重复: {rid}")
        seen.add(rid)


def _validate_rule(rule: dict) -> None:
    rid = rule.get("id")
    match = rule.get("match") or {}
    redact = rule.get("redact") or {}
    mtype = match.get("type")
    mode = redact.get("mode")
    if mtype not in MATCH_TYPES:
        raise RuleError(f"{rid}: 不支持的 match.type={mtype!r}")
    if mode not in REDACT_MODES:
        raise RuleError(f"{rid}: 不支持的 redact.mode={mode!r}")

    for key in ("pattern", "value_pattern", "pattern_after"):
        pattern = match.get(key)
        if pattern:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise RuleError(f"{rid}: {key} 正则非法: {exc}") from exc


def compile_pattern(pattern: str) -> re.Pattern:
    return _PATTERN_CACHE.setdefault(pattern, re.compile(pattern))


_PATTERN_CACHE: dict[str, re.Pattern] = {}