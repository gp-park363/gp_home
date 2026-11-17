"""관리자 견적: 목록(상태·담당·기간·검색), 상세, 답변 발송, 메모, 상태·담당 변경, 첨부, 삭제."""

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
from starlette.datastructures import FormData, UploadFile

from app import content
from app.db import DbSession
from app.models import Inquiry, InquiryFile, InquiryReply, InquiryReplyFile, User
from app.routers.admin.deps import AdminUser, CurrentUser, Page
from app.services import inquiry_admin as service
from app.services import storage
from app.templating import is_htmx, templates

log = logging.getLogger(__name__)
router = APIRouter(prefix="/inquiries")

PAGE_SIZE = 20


def _staff(db) -> list[User]:
    return list(db.scalars(select(User).where(User.is_active).order_by(User.name)))


def _get(db, inquiry_id: int) -> Inquiry:
    inq = db.get(Inquiry, inquiry_id)
    if inq is None:
        raise HTTPException(404)
    return inq


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def filters_dep(
    status: str = "",
    assignee: str = "",
    start: str = "",
    end: str = "",
    q: Annotated[str, Query(max_length=100)] = "",
) -> service.Filters:
    return service.Filters(
        status=status if status in content.INQUIRY_STATUSES else "",
        assignee=assignee if assignee in ("me", "none") or assignee.isdigit() else "",
        start=_date(start),
        end=_date(end),
        q=q,
    )


FiltersDep = Annotated[service.Filters, Depends(filters_dep)]


@router.get("/", response_class=HTMLResponse)
def inquiry_list(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    f: FiltersDep,
    page: Annotated[int, Query(ge=1, le=10000)] = 1,
):
    stmt = f.query(user)
    pg = Page(page, PAGE_SIZE, db.scalar(select(func.count()).select_from(stmt.subquery())))
    rows = db.scalars(
        stmt.order_by(Inquiry.created_at.desc(), Inquiry.id.desc()).limit(pg.size).offset(pg.offset)
    ).all()
    reply_counts = dict(
        db.execute(
            select(InquiryReply.inquiry_id, func.count())
            .where(InquiryReply.inquiry_id.in_([r.id for r in rows]), InquiryReply.kind == "reply")
            .group_by(InquiryReply.inquiry_id)
        ).all()
    )
    ctx = {
        "title": "견적 관리",
        "section": "inquiries",
        "user": user,
        "rows": rows,
        "reply_counts": reply_counts,
        "page": pg,
        "f": f,
        "counts": f.status_counts(db, user),
        "staff": _staff(db),
        "statuses": content.INQUIRY_STATUSES,
    }
    # 필터를 바꾸면 결과 영역만 교체합니다 (hx-push-url로 주소도 갱신)
    tpl = "admin/inquiries/_results.html" if is_htmx(request) else "admin/inquiries/list.html"
    return templates.TemplateResponse(request, tpl, ctx)


def _detail_ctx(db, inq: Inquiry, user: User, **extra) -> dict:
    return {
        "title": f"{inq.number} {inq.title}",
        "section": "inquiries",
        "user": user,
        "inq": inq,
        "staff": _staff(db),
        "statuses": content.INQUIRY_STATUSES,
        "reply_max_files": service.REPLY_MAX_FILES,
        "allowed_ext": ",".join(f".{e}" for e in sorted(service.ALLOWED_EXTENSIONS)),
        **extra,
    }


@router.get("/{inquiry_id:int}", response_class=HTMLResponse)
def inquiry_detail(request: Request, db: DbSession, user: CurrentUser, inquiry_id: int):
    inq = _get(db, inquiry_id)
    return templates.TemplateResponse(
        request, "admin/inquiries/detail.html", _detail_ctx(db, inq, user)
    )


def _updated(request: Request, db, inq: Inquiry, user: User, **extra) -> Response:
    """변경 후 응답: 처리 이력을 다시 그리고, 상태·담당 표시는 OOB로 함께 갱신합니다."""
    db.commit()
    res = templates.TemplateResponse(
        request, "admin/inquiries/_updated.html", _detail_ctx(db, inq, user, **extra)
    )
    if extra.get("composer_reset"):
        res.headers["HX-Trigger"] = "composer-reset"
    return res


async def _form(request: Request) -> FormData:
    return await request.form(max_files=service.REPLY_MAX_FILES + 2, max_fields=20)


FormDep = Annotated[FormData, Depends(_form)]


@router.post("/{inquiry_id:int}/status", response_class=HTMLResponse)
def set_status(request: Request, db: DbSession, user: CurrentUser, inquiry_id: int, data: FormDep):
    inq = _get(db, inquiry_id)
    service.change_status(db, inq, user, str(data.get("status", "")))
    return _updated(request, db, inq, user)


@router.post("/{inquiry_id:int}/assignee", response_class=HTMLResponse)
def set_assignee(
    request: Request, db: DbSession, user: CurrentUser, inquiry_id: int, data: FormDep
):
    inq = _get(db, inquiry_id)
    raw = str(data.get("assignee_id", ""))
    assignee = db.get(User, int(raw)) if raw.isdigit() else None
    if assignee is not None and not assignee.is_active:
        raise HTTPException(400)
    service.assign(db, inq, user, assignee)
    return _updated(request, db, inq, user)


@router.post("/{inquiry_id:int}/replies", response_class=HTMLResponse)
def add_reply(request: Request, db: DbSession, user: CurrentUser, inquiry_id: int, data: FormDep):
    """고객 답변(메일 발송) 또는 내부 메모."""
    inq = _get(db, inquiry_id)
    kind = data.get("kind")
    body = str(data.get("body", "")).strip()
    uploads = [u for u in data.getlist("files") if isinstance(u, UploadFile) and u.filename]

    error = None
    if kind not in ("reply", "memo"):
        raise HTTPException(400)
    if not body:
        error = "내용을 입력해 주세요."
    elif len(body) > 20000:
        error = "내용이 너무 깁니다."
    elif kind == "reply":
        error = service.check_reply_files([(u.filename, u.size or 0) for u in uploads])
    if error:
        return templates.TemplateResponse(
            request,
            "admin/inquiries/_composer_error.html",
            {"error": error},
            headers={"HX-Retarget": "#composer-error", "HX-Reswap": "outerHTML"},
        )

    if kind == "memo":
        service.add_memo(db, inq, user, body)
        return _updated(request, db, inq, user, composer_reset=True)

    saved: list[str] = []
    try:
        files = []
        for u in uploads:
            path = storage.save_private(u.file, u.filename, "replies")
            saved.append(path)
            files.append(
                (storage.safe_name(u.filename), path, u.size or 0, (u.content_type or "")[:100])
            )
        reply = service.add_reply(db, inq, user, body, files)
        db.commit()
    except Exception:
        db.rollback()
        for path in saved:
            storage.delete_private(path)
        raise
    sent = service.send_reply(inq, reply, user)
    log.info("견적 %s 답변 %s (메일 %s)", inq.number, reply.id, "성공" if sent else "실패")
    return _updated(request, db, inq, user, composer_reset=True, mail_failed=not sent)


@router.post("/{inquiry_id:int}/replies/{reply_id}/resend", response_class=HTMLResponse)
def resend_reply(
    request: Request, db: DbSession, user: CurrentUser, inquiry_id: int, reply_id: int
):
    inq = _get(db, inquiry_id)
    reply = db.get(InquiryReply, reply_id)
    if reply is None or reply.inquiry_id != inq.id or reply.kind != "reply":
        raise HTTPException(404)
    author = db.get(User, reply.author_id) if reply.author_id else None
    sent = service.send_reply(inq, reply, author or user)
    return _updated(request, db, inq, user, mail_failed=not sent)


@router.get("/{inquiry_id:int}/files/{file_id}")
def download_file(db: DbSession, user: CurrentUser, inquiry_id: int, file_id: int):
    f = db.get(InquiryFile, file_id)
    if f is None or f.inquiry_id != inquiry_id:
        raise HTTPException(404)
    return storage.download_response(f.path, f.original_name, f.content_type)


@router.get("/{inquiry_id:int}/reply-files/{file_id}")
def download_reply_file(db: DbSession, user: CurrentUser, inquiry_id: int, file_id: int):
    f = db.get(InquiryReplyFile, file_id)
    if f is None or f.reply.inquiry_id != inquiry_id:
        raise HTTPException(404)
    return storage.download_response(f.path, f.original_name, f.content_type)


@router.post("/{inquiry_id:int}/delete")
def delete_inquiry(request: Request, db: DbSession, user: AdminUser, inquiry_id: int):
    """스팸·중복 접수 삭제 (관리자만). 첨부 파일도 함께 지웁니다."""
    inq = _get(db, inquiry_id)
    number = inq.number
    paths = service.delete(db, inq)
    db.commit()
    for path in paths:
        storage.delete_private(path)
    log.warning("견적 삭제: %s (by %s)", number, user.email)
    url = "/admin/inquiries/"
    if is_htmx(request):
        return Response(headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)
