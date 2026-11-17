"""쇼룸: 목록(필터·무한 스크롤), 상세."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import Select, func, select

from app.content import BOX_TYPES, INDUSTRIES
from app.db import DbSession
from app.models import PortfolioItem
from app.templating import is_htmx, templates

router = APIRouter(prefix="/portfolio")

PAGE_SIZE = 12


def _filtered(box_type: str | None, industry: str | None) -> Select:
    q = select(PortfolioItem).where(PortfolioItem.is_published)
    if box_type:
        q = q.where(PortfolioItem.box_type == box_type)
    if industry:
        q = q.where(PortfolioItem.industry == industry)
    return q


def _counts(db, column, **filters) -> dict[str, int]:
    """필터 옵션 옆에 보여 줄 건수 (다른 쪽 필터는 적용한 상태)."""
    q = _filtered(**filters).with_only_columns(column, func.count()).group_by(column)
    return dict(db.execute(q).all())


def _clean(value: str | None, allowed: dict[str, str]) -> str | None:
    return value if value in allowed else None


@router.get("/", response_class=HTMLResponse)
def portfolio_list(
    request: Request,
    db: DbSession,
    box_type: Annotated[str | None, Query()] = None,
    industry: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
):
    box_type = _clean(box_type, BOX_TYPES)
    industry = _clean(industry, INDUSTRIES)
    q = _filtered(box_type, industry)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    items = db.scalars(
        q.order_by(PortfolioItem.sort_order.desc(), PortfolioItem.id.desc())
        .limit(PAGE_SIZE)
        .offset((page - 1) * PAGE_SIZE)
    ).all()

    ctx = {
        "items": items,
        "total": total,
        "page": page,
        "has_more": page * PAGE_SIZE < total,
        "box_type": box_type,
        "industry": industry,
        "box_types": BOX_TYPES,
        "industries": INDUSTRIES,
    }

    # htmx 조각 응답 (뒤로 가기 복원 요청은 전체 페이지)
    fragment = is_htmx(request) and not request.headers.get("HX-History-Restore-Request")
    if fragment and page > 1:  # 무한 스크롤: 카드 + 다음 감지 영역
        return templates.TemplateResponse(request, "portfolio/_cards.html", ctx)

    ctx["box_counts"] = _counts(db, PortfolioItem.box_type, box_type=None, industry=industry)
    ctx["industry_counts"] = _counts(db, PortfolioItem.industry, box_type=box_type, industry=None)
    if fragment:  # 필터 변경: 필터 영역 + 결과 영역
        return templates.TemplateResponse(request, "portfolio/_browser.html", ctx)

    ctx.update(
        active="portfolio",
        title="쇼룸",
        description="좋은상자에서 직접 제작한 패키지 박스 사례 — 박스형태·업종별로 찾아보세요.",
    )
    return templates.TemplateResponse(request, "portfolio/list.html", ctx)


@router.get("/{item_id}", response_class=HTMLResponse)
def portfolio_detail(request: Request, db: DbSession, item_id: int):
    item = db.get(PortfolioItem, item_id)
    if item is None or not item.is_published:
        raise HTTPException(404)
    related = db.scalars(
        _filtered(item.box_type, None)
        .where(PortfolioItem.id != item.id)
        .order_by(PortfolioItem.sort_order.desc(), PortfolioItem.id.desc())
        .limit(4)
    ).all()
    return templates.TemplateResponse(
        request,
        "portfolio/detail.html",
        {
            "item": item,
            "related": related,
            "active": "portfolio",
            "title": f"{item.name} — {item.box_type_label}",
            "description": item.description or f"{item.name} 패키지 박스 제작 사례",
        },
    )
