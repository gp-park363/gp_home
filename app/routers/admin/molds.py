"""관리자 목형: 목록·검색, 등록, 줄 단위 수정(htmx), 엑셀 일괄 등록·내려받기."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, or_, select
from starlette.datastructures import UploadFile

from app.content import BOX_TYPES
from app.db import DbSession
from app.models import Mold
from app.routers.admin.deps import CurrentUser, Page
from app.services import mold_import
from app.templating import is_htmx, templates

router = APIRouter(prefix="/molds")

PAGE_SIZE = 50
MAX_UPLOAD = 5 * 1024 * 1024


def _get(db, mold_id: int) -> Mold:
    mold = db.get(Mold, mold_id)
    if mold is None:
        raise HTTPException(404)
    return mold


@router.get("/", response_class=HTMLResponse)
def mold_list(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    box_type: str = "",
    active: str = "",
    q: Annotated[str, Query(max_length=50)] = "",
    page: Annotated[int, Query(ge=1, le=10000)] = 1,
):
    stmt = select(Mold)
    if box_type in BOX_TYPES:
        stmt = stmt.where(Mold.box_type == box_type)
    if active in ("1", "0"):
        stmt = stmt.where(Mold.is_active == (active == "1"))
    if q := q.strip():
        # "120x80x40"처럼 치수로도 찾습니다 (각 ±5mm)
        dims = [p for p in q.lower().replace("×", "x").replace("*", "x").split("x") if p.strip()]
        if len(dims) == 3 and all(p.strip().isdigit() for p in dims):
            w, d, h = (int(p) for p in dims)
            stmt = stmt.where(
                func.abs(Mold.width - w) <= 5,
                func.abs(Mold.depth - d) <= 5,
                func.abs(Mold.height - h) <= 5,
            )
        else:
            stmt = stmt.where(or_(Mold.code.ilike(f"%{q}%"), Mold.memo.ilike(f"%{q}%")))
    pg = Page(page, PAGE_SIZE, db.scalar(select(func.count()).select_from(stmt.subquery())))
    rows = db.scalars(
        stmt.order_by(Mold.code.nulls_last(), Mold.id).limit(pg.size).offset(pg.offset)
    ).all()
    ctx = {
        "title": "목형 관리",
        "section": "molds",
        "user": user,
        "rows": rows,
        "page": pg,
        "f": {"box_type": box_type, "active": active, "q": q},
        "box_types": BOX_TYPES,
    }
    tpl = "admin/molds/_results.html" if is_htmx(request) else "admin/molds/list.html"
    return templates.TemplateResponse(request, tpl, ctx)


def _clean(db, form: dict, mold: Mold | None = None) -> tuple[dict, str | None]:
    try:
        data = mold_import.parse_row(form)
    except ValueError as e:
        return {}, str(e)
    if data["code"]:
        other = db.scalar(select(Mold).where(Mold.code == data["code"]))
        if other is not None and other is not mold:
            return {}, f"목형번호 {data['code']}는 이미 있습니다."
    return data, None


async def _values(request: Request) -> dict:
    form = await request.form()
    values = {k: v for k, v in form.items() if isinstance(v, str)}
    values["active"] = "y" if values.get("active") else "n"
    return values


def _row(request, mold: Mold, tpl="admin/molds/_row.html", **extra):
    return templates.TemplateResponse(request, tpl, {"m": mold, "box_types": BOX_TYPES, **extra})


@router.post("/", response_class=HTMLResponse)
async def create_mold(request: Request, db: DbSession, user: CurrentUser):
    values = await _values(request)
    data, error = _clean(db, values)
    if error:
        return templates.TemplateResponse(
            request,
            "admin/molds/_form_error.html",
            {"error": error},
            headers={"HX-Retarget": "#new-mold-error", "HX-Reswap": "outerHTML"},
        )
    mold = Mold(**data)
    db.add(mold)
    db.commit()
    res = _row(request, mold, created=True)
    res.headers["HX-Trigger"] = "mold-created"
    return res


@router.get("/{mold_id:int}/row", response_class=HTMLResponse)
def mold_row(request: Request, db: DbSession, user: CurrentUser, mold_id: int):
    return _row(request, _get(db, mold_id))


@router.get("/{mold_id:int}/edit", response_class=HTMLResponse)
def mold_edit(request: Request, db: DbSession, user: CurrentUser, mold_id: int):
    return _row(request, _get(db, mold_id), "admin/molds/_edit_row.html", v=None)


@router.post("/{mold_id:int}", response_class=HTMLResponse)
async def update_mold(request: Request, db: DbSession, user: CurrentUser, mold_id: int):
    mold = _get(db, mold_id)
    values = await _values(request)
    data, error = _clean(db, values, mold)
    if error:
        return _row(request, mold, "admin/molds/_edit_row.html", v=values, error=error)
    for k, v in data.items():
        setattr(mold, k, v)
    db.commit()
    return _row(request, mold)


@router.delete("/{mold_id:int}", response_class=HTMLResponse)
def delete_mold(db: DbSession, user: CurrentUser, mold_id: int):
    """목형 삭제. 이 목형을 고른 견적은 목형 연결만 풀립니다."""
    db.delete(_get(db, mold_id))
    db.commit()
    return HTMLResponse("")


@router.post("/import", response_class=HTMLResponse)
async def import_molds(request: Request, db: DbSession, user: CurrentUser):
    form = await request.form(max_files=1)
    upload = form.get("file")
    ctx: dict = {"result": None, "error": None}
    if not isinstance(upload, UploadFile) or not upload.filename:
        ctx["error"] = "파일을 골라 주세요."
    elif (upload.size or 0) > MAX_UPLOAD:
        ctx["error"] = "파일이 너무 큽니다 (5MB까지)."
    else:
        try:
            rows = mold_import.read_rows(upload.filename, await upload.read())
        except ValueError as e:
            ctx["error"] = str(e)
        else:
            result = mold_import.apply(db, rows)
            if result.errors:
                db.rollback()
            else:
                db.commit()
            ctx["result"] = result
    res = templates.TemplateResponse(request, "admin/molds/_import_result.html", ctx)
    if ctx["result"] and not ctx["result"].errors:
        res.headers["HX-Trigger"] = "molds-imported"  # 목록 새로고침
    return res


@router.get("/export.xlsx")
def export_molds(db: DbSession, user: CurrentUser):
    molds = db.scalars(select(Mold).order_by(Mold.code.nulls_last(), Mold.id)).all()
    filename = f"molds-{datetime.now():%Y%m%d}.xlsx"
    return Response(
        mold_import.export_xlsx(list(molds)),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
