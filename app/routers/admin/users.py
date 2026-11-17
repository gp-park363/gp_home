"""관리자 계정 관리 (관리자 권한): 목록, 추가, 이름·권한·사용 여부 수정, 비밀번호 초기화."""

import logging
import re
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.content import ROLES
from app.db import DbSession
from app.models import User
from app.routers.admin.deps import AdminUser
from app.services import auth
from app.templating import templates

log = logging.getLogger(__name__)
router = APIRouter(prefix="/users")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def temp_password() -> str:
    """임시 비밀번호: 헷갈리는 글자(0/O, 1/l)를 뺀 12자 + 숫자 보장."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(secrets.choice(alphabet) for _ in range(9)) + str(secrets.randbelow(900) + 100)


def _get(db, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404)
    return target


def _list(request, db, user, **extra):
    users = db.scalars(select(User).order_by(User.is_active.desc(), User.name)).all()
    return templates.TemplateResponse(
        request,
        "admin/users/list.html",
        {
            "title": "계정 관리",
            "section": "users",
            "user": user,
            "users": users,
            "roles": ROLES,
            "v": {"role": "sales"},
            "errors": {},
            **extra,
        },
        status_code=422 if extra.get("errors") else 200,
    )


@router.get("/", response_class=HTMLResponse)
def user_list(request: Request, db: DbSession, user: AdminUser):
    return _list(request, db, user)


@router.post("/", response_class=HTMLResponse)
async def create_user(request: Request, db: DbSession, user: AdminUser):
    form = await request.form()
    v = {k: str(form.get(k, "")).strip() for k in ("email", "name", "role")}
    v["email"] = auth.normalize_email(v["email"])
    errors = {}
    if not EMAIL_RE.match(v["email"]) or len(v["email"]) > 200:
        errors["email"] = "이메일 주소를 확인해 주세요."
    elif db.scalar(select(User).where(User.email == v["email"])):
        errors["email"] = "이미 등록된 이메일입니다."
    if not v["name"] or len(v["name"]) > 50:
        errors["name"] = "이름을 입력해 주세요."
    if v["role"] not in ROLES:
        errors["role"] = "권한을 골라 주세요."
    if errors:
        return _list(request, db, user, v=v, errors=errors)
    password = temp_password()
    db.add(
        User(
            email=v["email"],
            name=v["name"],
            role=v["role"],
            password_hash=auth.hash_password(password),
        )
    )
    db.commit()
    log.info("계정 추가: %s (%s) by %s", v["email"], v["role"], user.email)
    return _list(request, db, user, issued={"email": v["email"], "password": password})


@router.post("/{user_id:int}", response_class=HTMLResponse)
async def update_user(request: Request, db: DbSession, user: AdminUser, user_id: int):
    target = _get(db, user_id)
    form = await request.form()
    name = str(form.get("name", "")).strip()
    role = str(form.get("role", ""))
    active = bool(form.get("is_active"))
    if not name or len(name) > 50 or role not in ROLES:
        raise HTTPException(400)
    if target.id == user.id and (role != "admin" or not active):
        notice = "자기 계정의 관리자 권한이나 사용 여부는 바꿀 수 없습니다."
        return _list(request, db, user, notice=notice)
    if target.is_active and not active:
        target.session_version += 1  # 로그인 중이면 바로 끊깁니다
    target.name, target.role, target.is_active = name, role, active
    db.commit()
    return RedirectResponse("/admin/users/", status_code=303)


@router.post("/{user_id:int}/reset", response_class=HTMLResponse)
def reset_password(request: Request, db: DbSession, user: AdminUser, user_id: int):
    target = _get(db, user_id)
    password = temp_password()
    auth.set_password(target, password)
    db.commit()
    if target.id == user.id:
        request.session.update(auth.session_payload(user))
    log.info("비밀번호 초기화: %s by %s", target.email, user.email)
    return _list(request, db, user, issued={"email": target.email, "password": password})
