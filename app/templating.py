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


def kst(value, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """UTC 시각을 한국 시간 문자열로 (템플릿 필터 `| kst`)."""
    from zoneinfo import ZoneInfo

    return value.astimezone(ZoneInfo("Asia/Seoul")).strftime(fmt) if value else ""


templates.env.filters["kst"] = kst


def qs(request: Request, **updates) -> str:
    """현재 쿼리 문자열에 값을 바꿔 넣은 "?a=1&b=2" (빈 값은 뺍니다). 페이지 이동 링크용."""
    from urllib.parse import urlencode

    params = dict(request.query_params) | {k: str(v) for k, v in updates.items()}
    clean = {k: v for k, v in params.items() if v not in ("", "None")}
    return "?" + urlencode(clean) if clean else "?"


templates.env.globals["qs"] = qs
