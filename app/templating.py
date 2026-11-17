from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR, get_settings
from app.content import COMPANY, NAV

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals.update(settings=get_settings(), company=COMPANY, nav=NAV)


def is_htmx(request: Request) -> bool:
    """htmx 요청이면 전체 페이지 대신 조각(partial)만 렌더링할 때 사용합니다."""
    return request.headers.get("HX-Request") == "true"


def client_ip(request: Request) -> str:
    """방문자 IP. Cloudflare 경유 시 CF-Connecting-IP를 신뢰합니다."""
    return request.headers.get("CF-Connecting-IP") or (
        request.client.host if request.client else ""
    )
