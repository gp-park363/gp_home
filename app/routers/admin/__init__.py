"""관리자 화면 /admin/ (기획서 4.4)."""

from datetime import UTC, datetime, time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select

from app.db import DbSession
from app.models import Inquiry
from app.routers.admin import account, inquiries, molds, showroom, users
from app.routers.admin.deps import CurrentUser, check_origin
from app.services.inquiry import KST
from app.services.inquiry_admin import OPEN_STATUSES
from app.templating import templates

router = APIRouter(prefix="/admin", dependencies=[Depends(check_origin)])


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: DbSession, user: CurrentUser):
    today = datetime.combine(datetime.now(UTC).astimezone(KST).date(), time.min, tzinfo=KST)
    counts = dict(db.execute(select(Inquiry.status, func.count()).group_by(Inquiry.status)).all())
    open_ = select(Inquiry).where(Inquiry.status.in_(OPEN_STATUSES))
    recent = Inquiry.created_at.desc()
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "title": "대시보드",
            "section": "dashboard",
            "user": user,
            "counts": counts,
            "today_date": today.date().isoformat(),
            "today": db.scalar(select(func.count()).where(Inquiry.created_at >= today)),
            "mine": db.scalars(open_.where(Inquiry.assignee_id == user.id).order_by(recent)).all(),
            "unassigned": db.scalars(
                open_.where(Inquiry.assignee_id.is_(None)).order_by(recent).limit(10)
            ).all(),
        },
    )


router.include_router(account.router)
router.include_router(inquiries.router)
router.include_router(molds.router)
router.include_router(showroom.router)
router.include_router(users.router)
