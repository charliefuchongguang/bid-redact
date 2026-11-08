from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import Base, User
from app.db.session import SessionLocal, engine


def create_tables() -> None:
    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)


def seed_admin(db: Session) -> tuple[User, bool]:
    existing = db.scalar(select(User).where(User.username == settings.admin_username))
    if existing:
        return existing, False
    user = User(
        username=settings.admin_username,
        email=None,
        password_hash=hash_password(settings.admin_password),
        role="admin",
        is_active=True,
        must_change_password=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, True


def init_db() -> None:
    create_tables()
    from app.rules.store import seed_rules_if_empty

    with SessionLocal() as db:
        user, created = seed_admin(db)
        print(f"admin: id={user.id} username={user.username} created={created}")
        rule_version = seed_rules_if_empty(db)
        if rule_version:
            print(
                f"rules: version={rule_version.version} "
                f"status={rule_version.status} id={rule_version.id}"
            )
        else:
            print("rules: 未找到 rules/rules.yaml，跳过种子导入")


if __name__ == "__main__":
    init_db()