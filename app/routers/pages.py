"""공개 정적 페이지와 헬스 체크."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select, text

from app import content
from app.db import DbSession
from app.models import PortfolioItem
from app.templating import templates

router = APIRouter()


def render(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, ctx)


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: DbSession, p: int | None = None):
    # 기존 WordPress 글 주소(/?p=ID) → 새 상세 주소로 영구 이동
    if p is not None:
        item_id = db.scalar(select(PortfolioItem.id).where(PortfolioItem.wp_post_id == p))
        if item_id:
            return RedirectResponse(f"/portfolio/{item_id}", status_code=301)
    return render(
        request,
        "pages/home.html",
        active="home",
        business=content.BUSINESS,
        process=content.HOME_PROCESS,
    )


@router.get("/company/", response_class=HTMLResponse)
def company(request: Request):
    return render(
        request,
        "pages/company.html",
        active="company",
        title="회사소개",
        description="좋은상자 회사소개 — 연혁, 조직도, 김포 본사와 제2공장 오시는 길.",
        history=content.HISTORY,
        organization=content.ORGANIZATION,
    )


@router.get("/process/", response_class=HTMLResponse)
def process(request: Request):
    return render(
        request,
        "pages/process.html",
        active="process",
        title="제작과정",
        description=(
            "패키지 박스 제작과정 — 형태·사이즈·재질 구상부터 디자인, "
            "인쇄·코팅·후가공·합지·톰슨·접착 생산, 출하까지."
        ),
        overview=content.PROCESS_OVERVIEW,
        steps=content.PROCESS_STEPS,
    )


@router.get("/facilities/", response_class=HTMLResponse)
def facilities(request: Request):
    return render(
        request,
        "pages/facilities.html",
        active="facilities",
        title="보유장비",
        description="좋은상자 보유장비 — 인쇄기, 코팅기, 접착기, 종이재단기, 톰슨기, 샘플기.",
        facilities=content.FACILITIES,
    )


@router.get("/partials/recent-inquiries", response_class=HTMLResponse)
def recent_inquiries(request: Request):
    """메인 '실시간 문의' 위젯 (60초마다 갱신).

    TODO(견적 기능 단계): inquiries 테이블에서 최근 3건(제목, 접수일)을 조회합니다.
    """
    return render(request, "partials/recent_inquiries.html", items=[])


@router.get("/healthz")
def healthz(db: DbSession):
    """외부 가동 감시용. DB 연결까지 확인합니다."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "error", "db": "down"}, status_code=503)
    return {"status": "ok"}
