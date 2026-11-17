"""로그인·로그아웃·내 비밀번호 변경."""

import logging
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import DbSession
from app.routers.admin.deps import CurrentUser, safe_next
from app.services import auth
from app.templating import client_ip, templates

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, db: DbSession, next: str = ""):
    if auth.user_from_session(db, request.session):
        return RedirectResponse(safe_next(next), status_code=303)
    return templates.TemplateResponse(
        request, "admin/login.html", {"title": "로그인", "next": safe_next(next), "email": ""}
    )


@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    db: DbSession,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
):
    ip = client_ip(request)
    error = "이메일 또는 비밀번호가 맞지 않습니다."
    try:
        user = auth.authenticate(db, email, password, ip)
    except auth.LoginLocked:
        user = None
        error = "로그인 실패가 많아 잠시 막혔습니다. 15분 뒤 다시 시도해 주세요."
        log.warning("로그인 잠김: %s (%s)", email, ip)
    db.commit()
    if user is None:
        return templates.TemplateResponse(
            request,
            "admin/login.html",
            {"title": "로그인", "next": safe_next(next), "email": email, "error": error},
            status_code=400,
        )
    request.session.clear()
    request.session.update(auth.session_payload(user))
    log.info("관리자 로그인: %s (%s)", user.email, ip)
    return RedirectResponse(safe_next(next), status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


@router.get("/password", response_class=HTMLResponse)
def password_form(request: Request, user: CurrentUser):
    return templates.TemplateResponse(
        request, "admin/password.html", {"title": "비밀번호 변경", "user": user, "errors": {}}
    )


@router.post("/password", response_class=HTMLResponse)
def change_password(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    current: Annotated[str, Form()] = "",
    new: Annotated[str, Form()] = "",
    confirm: Annotated[str, Form()] = "",
):
    errors = {}
    if not auth.verify_password(user, current):
        errors["current"] = "현재 비밀번호가 맞지 않습니다."
    elif problem := auth.password_problem(new, confirm):
        errors["new"] = problem
    if errors:
        return templates.TemplateResponse(
            request,
            "admin/password.html",
            {"title": "비밀번호 변경", "user": user, "errors": errors},
            status_code=400,
        )
    auth.set_password(user, new)
    db.commit()
    # 다른 기기의 로그인은 끊고, 지금 브라우저는 유지합니다.
    request.session.update(auth.session_payload(user))
    ctx = {"title": "비밀번호 변경", "user": user, "errors": {}, "done": True}
    return templates.TemplateResponse(request, "admin/password.html", ctx)
