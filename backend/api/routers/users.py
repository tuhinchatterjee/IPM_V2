"""
User administration.

Everything here is administrator-only, enforced on the server. Hiding a button
is not access control: a Viewer who discovers this URL must be refused by the
API, not by the absence of a link.

Passwords never leave the server and are never returned. Setting one hashes it
with Argon2id; resetting one is an administrator action recorded in the log.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from backend.api.auth import Account, normalise_role
from backend.api.permissions import Principal, RequireAdmin, Role
from backend.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


def _validated_email(value: str) -> str:
    """Shape-checked, not deliverability-checked.

    Deliberately a few characters rather than a dependency: this field exists so
    a person can be recognised and contacted, and the only failure worth
    catching here is a typed mistake. Whether the mailbox accepts post is the
    mail server's business, and no regular expression settles it.
    """
    text = (value or "").strip()
    if not text:
        return ""
    local, _, domain = text.partition("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError(f"'{text}' does not look like an email address.")
    return text


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "storage_unavailable",
                "message": "User administration needs PostgreSQL."},
    )


def _not_found(user_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": f"User {user_id} does not exist."},
    )


def _view(row) -> dict:
    return {
        **Account(
            id=row.id, username=row.username,
            first_name=row.first_name or "", last_name=row.last_name or "",
            email=row.email or "", role=normalise_role(row.role),
            team=row.team or "", is_active=bool(row.is_active),
        ).to_dict(),
        "last_login_at": row.last_login_at.isoformat() if row.last_login_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=200)
    first_name: str = Field(default="", max_length=80)
    last_name: str = Field(default="", max_length=80)
    email: str = Field(default="", max_length=200)
    role: str = Field(default="ANALYST", max_length=24)
    team: str = Field(default="", max_length=120)

    @field_validator("email")
    @classmethod
    def _looks_like_an_address(cls, value: str) -> str:
        return _validated_email(value)


class UserPatch(BaseModel):
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=24)
    team: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None

    @field_validator("email")
    @classmethod
    def _looks_like_an_address(cls, value: str | None) -> str | None:
        return None if value is None else _validated_email(value)


class PasswordIn(BaseModel):
    password: str = Field(min_length=8, max_length=200)


@router.get("", summary="Everyone with an account")
def list_users(principal: Principal = RequireAdmin) -> dict:
    if not settings.has_database:
        raise _unavailable()
    from backend.db.engine import get_session
    from backend.db.models import User

    with get_session() as session:
        rows = session.query(User).order_by(User.username).all()
        return {
            "users": [_view(r) for r in rows],
            "roles": [
                {"role": r.value, "label": ROLE_LABEL[r], "can": ROLE_SUMMARY[r]}
                for r in Role
            ],
        }


ROLE_LABEL = {
    Role.ADMIN: "Administrator",
    Role.DATA_STEWARD: "Data steward",
    Role.ANALYST: "Analyst",
    Role.VIEWER: "Viewer",
}

#: One sentence each, so the person assigning a role can see what they are
#: handing over without opening a governance document.
ROLE_SUMMARY = {
    Role.ADMIN: (
        "Everything, including user accounts, governance and the Early Warning "
        "Model Lab."
    ),
    Role.DATA_STEWARD: (
        "Data Builder: onboard, map, harmonise and publish datasets, and decide "
        "which is authoritative. May run analyses."
    ),
    Role.ANALYST: (
        "Ask questions, run analyses, build Lenses and Playbooks, own Projects "
        "and Investigations."
    ),
    Role.VIEWER: "Read what others have produced. May not run or change anything.",
}


@router.post("", status_code=201, summary="Add a user")
def create_user(payload: UserIn, principal: Principal = RequireAdmin) -> dict:
    if not settings.has_database:
        raise _unavailable()
    from backend.auth.security import hash_password
    from backend.db.engine import get_session
    from backend.db.models import User

    role = normalise_role(payload.role)
    with get_session() as session:
        if session.query(User).filter(User.username == payload.username).first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "username_taken",
                        "message": f"'{payload.username}' already has an account."},
            )
        row = User(
            username=payload.username.strip(),
            password_hash=hash_password(payload.password),
            first_name=payload.first_name.strip(),
            last_name=payload.last_name.strip(),
            email=payload.email,
            role=role.value,
            team=payload.team.strip(),
            is_active=True,
        )
        session.add(row)
        session.flush()
        body = _view(row)
        session.commit()
    logger.info("User %s created by %s", body["username"], principal.user_id)
    return body


@router.patch("/{user_id}", summary="Edit a user")
def update_user(user_id: int, payload: UserPatch,
                principal: Principal = RequireAdmin) -> dict:
    if not settings.has_database:
        raise _unavailable()
    from backend.db.engine import get_session
    from backend.db.models import User

    with get_session() as session:
        row = session.get(User, user_id)
        if row is None:
            raise _not_found(user_id)

        # An administrator who removes their own last privilege locks the
        # product's only way back in. Refuse rather than let it happen.
        if payload.role is not None and normalise_role(payload.role) is not Role.ADMIN:
            _refuse_if_last_admin(session, row, "change the role of")
        if payload.is_active is False:
            _refuse_if_last_admin(session, row, "deactivate")

        if payload.first_name is not None:
            row.first_name = payload.first_name.strip()
        if payload.last_name is not None:
            row.last_name = payload.last_name.strip()
        if payload.email is not None:
            row.email = payload.email
        if payload.role is not None:
            row.role = normalise_role(payload.role).value
        if payload.team is not None:
            row.team = payload.team.strip()
        if payload.is_active is not None:
            row.is_active = payload.is_active
        body = _view(row)
        session.commit()
    return body


@router.post("/{user_id}/password", summary="Set a user's password")
def set_password(user_id: int, payload: PasswordIn,
                 principal: Principal = RequireAdmin) -> dict:
    if not settings.has_database:
        raise _unavailable()
    from backend.auth.security import hash_password
    from backend.db.engine import get_session
    from backend.db.models import User

    with get_session() as session:
        row = session.get(User, user_id)
        if row is None:
            raise _not_found(user_id)
        row.password_hash = hash_password(payload.password)
        session.commit()
    logger.info("Password for user %s reset by %s", user_id, principal.user_id)
    return {"user_id": user_id, "password_set": True}


def _refuse_if_last_admin(session, row, action: str) -> None:
    """Stop the product locking everybody out of its own administration."""
    from backend.db.models import User

    if normalise_role(row.role) is not Role.ADMIN:
        return
    others = (
        session.query(User)
        .filter(User.id != row.id, User.is_active.is_(True))
        .all()
    )
    if not any(normalise_role(o.role) is Role.ADMIN for o in others):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "last_administrator",
                "message": (
                    f"{row.username} is the only active administrator, so you "
                    f"cannot {action} them. Promote somebody else first."
                ),
            },
        )


__all__ = ["router"]
