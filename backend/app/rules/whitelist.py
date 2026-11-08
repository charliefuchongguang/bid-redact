from __future__ import annotations

import re

from app.rules.checks import verify
from app.rules.loader import RuleSet, compile_pattern


def whitelist_hit(value: str, context: str, rule: dict, ruleset: RuleSet) -> str | None:
    """返回命中的白名单 id；未命中返回 None。"""
    if not value:
        return None
    honored = set((rule.get("match") or {}).get("whitelist") or [])

    for item in ruleset.whitelist:
        if item.get("detect"):
            continue
        kind = item.get("type", "value")
        wid = item.get("id", "?")

        if kind == "value":
            pattern = item.get("pattern")
            if not pattern:
                continue
            if not compile_pattern(pattern).fullmatch(value):
                continue
            if any(kw in context for kw in item.get("exclude_context") or []):
                continue
            excluded = False
            for check in item.get("exclude_if_checks") or []:
                if verify(check, value):
                    excluded = True
                    break
            if excluded:
                continue
            return wid

        if kind == "context":
            if wid not in honored:
                continue
            pattern = item.get("pattern")
            if pattern and not compile_pattern(pattern).fullmatch(value):
                continue
            keywords = item.get("keywords") or []
            if not keywords:
                return wid
            if any(kw in context for kw in keywords):
                return wid
    return None