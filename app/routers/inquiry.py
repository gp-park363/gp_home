"""견적문의: 3단계 폼, 필드·단계 검증, 목형 추천, 평량 연동, 접수."""

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from starlette.datastructures import FormData, UploadFile

from app import content
from app.db import DbSession
from app.models import Inquiry, Mold, PortfolioItem
from app.services import inquiry as service
from app.services import inquiry_form as form
from app.services import mold_match, storage, turnstile
from app.templating import client_ip, is_htmx, templates

log = logging.getLogger(__name__)
router = APIRouter(prefix="/inquiry")

HONEYPOT = "homepage"  # 화면에 보이지 않는 칸. 채워져 있으면 자동 등록으로 봅니다.


async def read_form(request: Request) -> FormData:
    return await request.form(max_files=form.MAX_FILES + 5, max_fields=200)


FormDep = Annotated[FormData, Depends(read_form)]


def _values(data: FormData) -> dict[str, str]:
    return {k: v for k, v in data.multi_items() if isinstance(v, str)}


def _mold_error(db, clean: dict, errors: dict) -> None:
    mold_id = clean.get("mold_id")
    if mold_id is not None:
        mold = db.get(Mold, mold_id)
        if mold is None or not mold.is_active:
            clean["mold_id"] = None
            errors["mold_id"] = "선택한 목형을 찾을 수 없습니다. 다시 선택해 주세요."


def _box_cards(db) -> list[dict]:
    """박스형태 카드: 같은 형태의 쇼룸 사진을 썸네일로 씁니다 (도면 이미지가 생기면 교체)."""
    thumbs: dict[str, str] = {}
    items = db.scalars(
        select(PortfolioItem)
        .where(PortfolioItem.is_published)
        .order_by(PortfolioItem.sort_order.desc(), PortfolioItem.id.desc())
    )
    for item in items:
        if item.box_type not in thumbs and item.thumb_url:
            thumbs[item.box_type] = item.thumb_url
    return [
        {"key": k, "label": label, "help": content.BOX_TYPE_HELP[k], "thumb": thumbs.get(k)}
        for k, label in content.BOX_TYPES.items()
    ]


def _errors_response(request: Request, errors: dict[str, str], names, step: int | None = None):
    """htmx 응답: 각 필드 오류 칸을 OOB로 교체하고, 오류가 있으면 해당 단계로 이동시킵니다."""
    res = templates.TemplateResponse(
        request, "inquiry/_errors.html", {"names": names, "errors": errors}
    )
    if errors:
        target = step or form.first_error_step(errors)
        res.headers["HX-Trigger"] = f'{{"inquiry-invalid": {{"step": {target}}}}}'
    return res


def _render_form(request: Request, db, values: dict, errors: dict | None = None, status=200):
    portfolio = None
    pid = values.get("portfolio_item_id") or ""
    if pid.isdigit():
        portfolio = db.get(PortfolioItem, int(pid))
        if portfolio and not portfolio.is_published:
            portfolio = None
    errors = errors or {}
    return templates.TemplateResponse(
        request,
        "inquiry/form.html",
        {
            "active": "inquiry",
            "title": "견적문의",
            "description": (
                "패키지 박스 제작 견적문의 — 박스형태·사이즈·재질을 알려 주시면 "
                "비슷한 규격의 보유 목형과 함께 빠르게 상담해 드립니다."
            ),
            "v": values,
            "errors": errors,
            "step": form.first_error_step(errors) if errors else 1,
            "portfolio": portfolio,
            "box_cards": _box_cards(db),
            "weights": form.weights_for(values.get("material", "")),
            "steps": form.STEPS,
            "max_files": form.MAX_FILES,
            "max_file_size": form.MAX_FILE_SIZE,
            "allowed_ext": sorted(form.ALLOWED_EXTENSIONS),
            "content": content,
        },
        status_code=status,
    )


@router.get("/", response_class=HTMLResponse)
def inquiry_form(
    request: Request,
    db: DbSession,
    portfolio: Annotated[int | None, Query()] = None,
):
    values: dict[str, str] = {}
    # 쇼룸 상세의 "이 사양으로 견적 문의": 박스형태와 참고 사양을 미리 채웁니다.
    item = db.get(PortfolioItem, portfolio) if portfolio else None
    if item and item.is_published:
        values["portfolio_item_id"] = str(item.id)
        values["box_type"] = item.box_type
        values["title"] = f"{item.name} 같은 박스 제작 문의"
        spec_lines = [f"- {label}: {value}" for label, value in item.specs]
        ref = f"{item.name}({item.code})" if item.code else item.name
        values["content"] = "\n".join([f"[참고 사례] {ref}", *spec_lines, "", ""])
    return _render_form(request, db, values)


@router.post("/validate", response_class=HTMLResponse)
def validate_field(request: Request, db: DbSession, data: FormDep):
    """입력 칸을 벗어날 때 그 칸만 검증해 오류 문구를 돌려줍니다."""
    name = request.headers.get("HX-Trigger-Name", "")
    f = form.FIELD_MAP.get(name)
    if f is None:
        raise HTTPException(400)
    values = _values(data)
    clean, err = form.clean_field(f, values.get(name, ""), values)
    errors = {name: err} if err else {}
    if name == "mold_id" and not err:
        _mold_error(db, {name: clean}, errors)
    return templates.TemplateResponse(
        request, "inquiry/_error.html", {"name": name, "msg": errors.get(name, "")}
    )


@router.post("/step/{step}", response_class=HTMLResponse)
def validate_step(request: Request, db: DbSession, data: FormDep, step: int):
    """ "다음" 버튼: 해당 단계 항목을 검증하고, 통과하면 다음 단계로 넘어가게 합니다."""
    if step not in (1, 2):
        raise HTTPException(404)
    clean, errors = form.validate(_values(data), steps=(step,))
    if step == 1:
        _mold_error(db, clean, errors)
    names = [f.name for f in form.FIELDS if f.step == step]
    res = _errors_response(request, errors, names, step)
    if not errors:
        res.headers["HX-Trigger"] = f'{{"inquiry-step": {{"step": {step + 1}}}}}'
    return res


@router.get("/weights", response_class=HTMLResponse)
def weight_options(request: Request, material: str = "", weight: str = ""):
    """종이재질을 바꾸면 그 재질에 맞는 평량만 보여 줍니다."""
    return templates.TemplateResponse(
        request,
        "inquiry/_weight.html",
        {
            "weights": form.weights_for(material),
            "v": {"material": material, "weight": weight},
            "content": content,
        },
    )


@router.get("/molds", response_class=HTMLResponse)
def mold_suggestions(
    request: Request,
    db: DbSession,
    box_type: str = "",
    width: str = "",
    depth: str = "",
    height: str = "",
    mold_id: str = "",
):
    """가로·세로·높이를 입력하면 비슷한 규격의 보유 목형을 보여 줍니다."""
    f = form.FIELD_MAP
    dims = [
        form.clean_field(f[n], raw, {})
        for n, raw in (("width", width), ("depth", depth), ("height", height))
    ]
    ready = all(v is not None and err is None for v, err in dims)
    matches = []
    if ready:
        box = box_type if box_type in content.BOX_TYPES else None
        matches = mold_match.find_similar(db, box, *(v for v, _ in dims))
    return templates.TemplateResponse(
        request,
        "inquiry/_molds.html",
        {
            "ready": ready,
            "matches": matches,
            "selected": mold_id,
            "box_label": content.BOX_TYPES.get(box_type, ""),
        },
    )


@router.post("/", response_class=HTMLResponse)
def submit(request: Request, db: DbSession, data: FormDep, background: BackgroundTasks):
    values = _values(data)
    uploads = [u for u in data.getlist("files") if isinstance(u, UploadFile) and u.filename]
    clean, errors = form.validate(values)
    _mold_error(db, clean, errors)

    file_errors = [e for u in uploads if (e := form.check_file(u.filename, u.size or 0))]
    if len(uploads) > form.MAX_FILES:
        file_errors.insert(0, f"첨부는 최대 {form.MAX_FILES}개까지 가능합니다.")
    if file_errors:
        errors["files"] = " ".join(file_errors)

    ip = client_ip(request)
    if values.get(HONEYPOT):
        errors["form"] = "접수할 수 없습니다. 전화로 문의해 주세요."
    elif not errors and not turnstile.verify(values.get("cf-turnstile-response", ""), ip):
        errors["captcha"] = "자동 등록 방지 확인에 실패했습니다. 다시 시도해 주세요."

    if errors:
        if is_htmx(request):
            names = [*form.FIELD_MAP, "files", "captcha", "form"]
            return _errors_response(request, errors, names)
        values.pop("cf-turnstile-response", None)
        return _render_form(request, db, values, errors, status=422)

    pid = values.get("portfolio_item_id", "")
    portfolio = db.get(PortfolioItem, int(pid)) if pid.isdigit() else None

    saved: list[str] = []
    try:
        files = []
        for u in uploads:
            path = storage.save_private(u.file, u.filename, "inquiries")
            saved.append(path)
            files.append(
                (storage.safe_name(u.filename), path, u.size or 0, (u.content_type or "")[:100])
            )
        inq = service.create(
            db,
            clean,
            files,
            ip=ip,
            user_agent=request.headers.get("user-agent", ""),
            portfolio_item_id=portfolio.id if portfolio and portfolio.is_published else None,
        )
        db.commit()
    except Exception:
        db.rollback()
        for path in saved:
            storage.delete_private(path)
        raise

    log.info("견적 접수 %s (첨부 %d)", inq.number, len(files))
    background.add_task(service.notify, inq.id)
    url = f"/inquiry/complete?t={service.complete_token(inq.id)}"
    if is_htmx(request):
        return Response(headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


@router.get("/complete", response_class=HTMLResponse)
def complete(request: Request, db: DbSession, t: str = ""):
    inquiry_id = service.read_complete_token(t)
    inq = db.get(Inquiry, inquiry_id) if inquiry_id else None
    if inq is None:
        return RedirectResponse("/inquiry/", status_code=303)
    return templates.TemplateResponse(
        request,
        "inquiry/complete.html",
        {
            "active": "inquiry",
            "title": "견적문의 접수 완료",
            "inq": inq,
            "masked_email": _mask_email(inq.email),
        },
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"},
    )


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:2]}{'*' * max(len(local) - 2, 1)}@{domain}"
