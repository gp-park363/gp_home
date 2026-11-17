from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import BASE_DIR, get_settings
from app.routers import admin, inquiry, pages, portfolio
from app.routers.admin.deps import (
    AdminOnly,
    LoginRequired,
    admin_only_handler,
    login_required_handler,
)
from app.services.auth import SESSION_COOKIE, SESSION_MAX_AGE


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="좋은상자",
        docs_url=None if settings.is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_prod else "/openapi.json",
    )

    # 관리자 로그인 세션: 서명된 쿠키, /admin 경로에만 전송
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=SESSION_COOKIE,
        max_age=SESSION_MAX_AGE,
        path="/admin",
        same_site="lax",
        https_only=settings.is_prod,
    )

    @app.middleware("http")
    async def admin_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/admin"):
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
            response.headers["X-Frame-Options"] = "DENY"
        return response

    app.add_exception_handler(LoginRequired, login_required_handler)
    app.add_exception_handler(AdminOnly, admin_only_handler)

    app.include_router(pages.router)
    app.include_router(portfolio.router)
    app.include_router(inquiry.router)
    app.include_router(admin.router)

    # 운영에서는 Nginx가 /static, /media를 직접 서빙합니다.
    # 로컬에서 uvicorn만 띄우거나 테스트할 때를 위한 대체 경로입니다.
    if not settings.is_prod:
        app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
        settings.media_public.mkdir(parents=True, exist_ok=True)
        app.mount("/media", StaticFiles(directory=settings.media_public), name="media")

    return app


app = create_app()
