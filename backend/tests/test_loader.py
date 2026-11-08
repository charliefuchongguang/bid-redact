from __future__ import annotations

from pathlib import Path

from app.rules.loader import load_rules

RULES = Path(__file__).resolve().parents[2] / "rules" / "rules.yaml"


def test_rules_load_and_on_key_normalized():
    rs = load_rules(RULES)
    assert rs.version == "1.4"
    assert len(rs.whitelist) == 7
    assert len(rs.rules) == 29
    assert rs.rule("RED-03")["match"].get("on") == "auto"
    assert rs.rule("RED-01")["match"].get("verify") == "gb11643"


def test_all_rules_have_valid_types():
    rs = load_rules(RULES)
    for rule in rs.rules:
        assert rule["match"]["type"] in {"regex", "semantic", "table", "image"}
        assert rule["redact"]["mode"] in {"rect", "card", "image", "cell"}