from __future__ import annotations

from pathlib import Path

from app.rules.loader import load_rules
from app.rules.whitelist import whitelist_hit

RULES = Path(__file__).resolve().parents[2] / "rules" / "rules.yaml"


def _ruleset():
    return load_rules(RULES)


def test_credit_code_is_whitelisted():
    rs = _ruleset()
    rule = rs.rule("RED-08")
    assert whitelist_hit("91230100MA1B12345X", "统一社会信用代码", rule, rs) == "WL-01"


def test_id_number_is_not_whitelisted_by_credit_code_rule():
    rs = _ruleset()
    rule = rs.rule("RED-01")
    # 该 18 位串能通过身份证校验，不能被 WL-01 吞掉
    assert whitelist_hit("11010519491231002X", "身份证号", rule, rs) is None


def test_wl07_requires_rule_opt_in():
    rs = _ruleset()
    amount_rule = rs.rule("RED-13")
    assert whitelist_hit("1500000.00", "招标控制价", amount_rule, rs) == "WL-07"

    other_rule = rs.rule("RED-08")
    assert whitelist_hit("1500000.00", "招标控制价", other_rule, rs) is None


def test_seal_whitelist_does_not_swallow_everything():
    rs = _ruleset()
    rule = rs.rule("RED-03")
    assert whitelist_hit("13800138000", "手机：13800138000", rule, rs) is None