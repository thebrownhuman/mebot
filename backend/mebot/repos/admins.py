from sqlalchemy import select
from sqlalchemy.orm import Session

from mebot.models import Admin, utcnow


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get(db: Session, admin_id: str) -> Admin | None:
    return db.scalar(select(Admin).where(Admin.id == admin_id, Admin.deleted_at.is_(None)))


def get_by_email(db: Session, email: str) -> Admin | None:
    return db.scalar(
        select(Admin).where(Admin.email == normalize_email(email), Admin.deleted_at.is_(None))
    )


def exists(db: Session) -> bool:
    return db.scalar(select(Admin.id).where(Admin.deleted_at.is_(None)).limit(1)) is not None


def create(db: Session, email: str, password_hash: str, bot_id: str | None = None) -> Admin:
    admin = Admin(email=normalize_email(email), password_hash=password_hash, bot_id=bot_id)
    db.add(admin)
    db.flush()
    return admin


def set_password_hash(db: Session, admin: Admin, password_hash: str) -> None:
    admin.password_hash = password_hash
    admin.updated_at = utcnow()
    db.flush()
