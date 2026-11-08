from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, RuleVersion
from app.rules.loader import validate_rules_dict
from app.rules.store import (
    activate_version,
    create_version,
    get_active_ruleset,
    next_version,
    payload_from_version,
    save_payload,
    seed_rules_if_empty,
)

RULES = Path(__file__).resolve().parents[2] / "rules" / "rules.yaml"


def make_session(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_seed_and_active_ruleset(tmp_path):
    db = make_session(tmp_path)
    try:
        row = seed_rules_if_empty(db, RULES)
        assert row is not None
        assert row.version == "1.4"
        assert row.status == "active"

        ruleset = get_active_ruleset(db)
        assert ruleset.version == "1.4"
        assert len(ruleset.rules) == 29
        assert len(ruleset.whitelist) == 7
        assert ruleset.rule("RED-03")["match"]["on"] == "auto"
    finally:
        db.close()


def test_draft_save_and_activate_keep_active_unchanged(tmp_path):
    db = make_session(tmp_path)
    try:
        active = seed_rules_if_empty(db, RULES)
        original = payload_from_version(db, active)

        draft_version = next_version(db, active.version)
        assert draft_version == "1.5"
        draft = create_version(db, original, status="draft", version=draft_version)
        db.commit()

        edited = payload_from_version(db, draft)
        edited["personal"][0]["name"] = "身份证号（测试）"
        save_payload(db, draft, edited)
        db.commit()

        still_active = db.scalar(select(RuleVersion).where(RuleVersion.status == "active"))
        assert still_active.id == active.id
        assert payload_from_version(db, still_active)["personal"][0]["name"] == "身份证号"

        activate_version(db, draft)
        db.commit()
        db.refresh(active)
        db.refresh(draft)
        assert active.status == "archived"
        assert draft.status == "active"
        assert get_active_ruleset(db).rule("RED-01")["name"] == "身份证号（测试）"
    finally:
        db.close()


def test_validation_rejects_bad_rule(tmp_path):
    db = make_session(tmp_path)
    try:
        active = seed_rules_if_empty(db, RULES)
        payload = payload_from_version(db, active)
        payload["personal"][0]["match"]["pattern"] = "("
        errors = validate_rules_dict(payload)
        assert any("正则非法" in err for err in errors)
    finally:
        db.close()