"""관리자 화면 공통: 로그인 확인, 권한, 요청 출처 확인, 페이지 나누기."""

import math
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import quote, urlsplit

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse, Response

from app.db import DbSession
from app.models import User
from app.services import auth
from app.templating import is_htmx, templates


class LoginRequired(Exception):
    pass


class AdminOnly(Exception):
    pass


def current_user(request: Request, db: DbSession) -> User:
    user = auth.user_from_session(db, request.session)
    if user is None:
        request.session.clear()
        raise LoginRequired
    request.state.user = user
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise AdminOnly
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def check_origin(request: Request) -> None:
    """다른 사이트에서 보낸 변경 요청 차단 (SameSite=Lax 쿠키에 더한 이중 방어)."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise AdminOnly


def safe_next(url: str | None) -> str:
    """로그인 후 돌아갈 주소: 관리자 화면 안쪽만 허용."""
    if url and url.startswith("/admin") and not url.startswith("//") and "\\" not in url:
        return url
    return "/admin/"


def login_required_handler(request: Request, exc: LoginRequired) -> Response:
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    url = f"/admin/login?next={quote(target)}"
    if is_htmx(request):
        return Response(status_code=401, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


def admin_only_handler(request: Request, exc: AdminOnly) -> Response:
    return templates.TemplateResponse(
        request,
        "admin/403.html",
        {"title": "권한 없음", "user": getattr(request.state, "user", None)},
        status_code=403,
    )


@dataclass
class Page:
    number: int
    size: int
    total: int

    @property
    def offset(self) -> int:
        return (self.number - 1) * self.size

    @property
    def pages(self) -> int:
        return max(1, math.ceil(self.total / self.size))

    def window(self, radius: int = 2) -> range:
        lo = max(1, self.number - radius)
        return range(lo, min(self.pages, lo + radius * 2) + 1)
