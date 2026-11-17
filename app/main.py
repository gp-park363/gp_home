from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR, get_settings
from app.routers import pages, portfolio


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="좋은상자",
        docs_url=None if settings.is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_prod else "/openapi.json",
    )

    app.include_router(pages.router)
    app.include_router(portfolio.router)

    # 운영에서는 Nginx가 /static, /media를 직접 서빙합니다.
    # 로컬에서 uvicorn만 띄우거나 테스트할 때를 위한 대체 경로입니다.
    if not settings.is_prod:
        app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
        settings.media_public.mkdir(parents=True, exist_ok=True)
        app.mount("/media", StaticFiles(directory=settings.media_public), name="media")

    return app


app = create_app()
