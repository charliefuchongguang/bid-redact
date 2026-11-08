from __future__ import annotations

from app.rules.checks import verify
from app.rules.loader import RuleSet, compile_pattern
from app.rules.normalize import extract_value_after
from app.rules.whitelist import whitelist_hit

MAX_HITS = 500
MAX_KEYWORD_HITS = 20


def run_text_test(ruleset: RuleSet, text: str) -> dict:
    hits: list[dict] = []
    stats: dict[str, int] = {}
    seen: set[tuple[str, int, int]] = set()

    for rule in ruleset.enabled_rules():
        match = rule.get("match") or {}
        mtype = match.get("type")
        if mtype not in ("regex", "semantic"):
            continue
        if mtype == "regex":
            found = _run_regex(rule, text, ruleset)
        else:
            found = _run_semantic(rule, text, ruleset)
        for hit in found:
            key = (hit["rule_id"], hit["start"], hit["end"])
            if key in seen:
                continue
            seen.add(key)
            hits.append(hit)
            stats[hit["rule_id"]] = stats.get(hit["rule_id"], 0) + 1
            if len(hits) >= MAX_HITS:
                return {"hits": hits, "stats": stats, "ruleset_version": ruleset.version}
    hits.sort(key=lambda h: (h["start"], h["end"]))
    return {"hits": hits, "stats": stats, "ruleset_version": ruleset.version}


def _run_regex(rule: dict, text: str, ruleset: RuleSet) -> list[dict]:
    match = rule.get("match") or {}
    pattern = match.get("pattern")
    if not pattern:
        return []
    regex = compile_pattern(pattern)
    verify_kind = match.get("verify")
    out: list[dict] = []
    for found in regex.finditer(text):
        value = found.group(0)
        if not value or not verify(verify_kind, value):
            continue
        line = _line_at(text, found.start())
        if _excluded(line, rule) or whitelist_hit(value, line, rule, ruleset):
            continue
        out.append(_hit(rule, "regex", value, found.start(), found.end(), line))
        if len(out) >= MAX_HITS:
            break
    return out


def _run_semantic(rule: dict, text: str, ruleset: RuleSet) -> list[dict]:
    match = rule.get("match") or {}
    keywords = [str(k) for k in (match.get("keywords") or []) if k]
    if not keywords:
        return []
    value_pattern = match.get("value_pattern") or match.get("pattern_after")
    scope = match.get("scope", "after")
    max_len = int(match.get("max_len", 60))
    out: list[dict] = []

    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        if line and not _excluded(line, rule):
            for keyword in keywords:
                start_at = 0
                hits = 0
                while hits < MAX_KEYWORD_HITS:
                    idx = line.find(keyword, start_at)
                    if idx == -1:
                        break
                    hits += 1
                    start_at = idx + len(keyword)
                    if scope == "block":
                        value = line.strip()
                        if not value or whitelist_hit(value, line, rule, ruleset):
                            continue
                        leading = len(line) - len(line.lstrip())
                        out.append(
                            _hit(
                                rule,
                                "semantic",
                                value,
                                offset + leading,
                                offset + leading + len(value),
                                line,
                            )
                        )
                        continue
                    extracted = extract_value_after(
                        line, idx + len(keyword), value_pattern, max_len
                    )
                    if not extracted:
                        continue
                    value, v_start, v_end = extracted
                    if not value or whitelist_hit(value, line, rule, ruleset):
                        continue
                    out.append(
                        _hit(
                            rule,
                            "semantic",
                            value,
                            offset + v_start,
                            offset + v_end,
                            line,
                        )
                    )
                    if len(out) >= MAX_HITS:
                        return out
        offset += len(raw_line)
    return out


def _hit(rule: dict, mtype: str, value: str, start: int, end: int, line: str) -> dict:
    return {
        "rule_id": rule["id"],
        "name": rule.get("name") or rule["id"],
        "category": rule.get("category") or "unknown",
        "match_type": mtype,
        "value": value,
        "start": start,
        "end": end,
        "line": line[:200],
    }


def _line_at(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end == -1:
        end = len(text)
    return text[start:end]


def _excluded(line: str, rule: dict) -> bool:
    excludes = (rule.get("match") or {}).get("exclude_context") or []
    return any(k in line for k in excludes)