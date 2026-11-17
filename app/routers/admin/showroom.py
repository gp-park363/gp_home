"""관리자 쇼룸 편집 (관리자 권한): 목록, 등록·수정, 이미지 추가·삭제·순서, 공개 전환."""

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from starlette.datastructures import FormData, UploadFile

from app.content import BOX_TYPES, INDUSTRIES
from app.db import DbSession
from app.models import PortfolioImage, PortfolioItem
from app.routers.admin.deps import AdminUser
from app.services import images
from app.templating import is_htmx, templates

log = logging.getLogger(__name__)
router = APIRouter(prefix="/showroom")

TEXT_FIELDS = (  # (이름, 라벨, 최대 길이)
    ("name", "품명", 100),
    ("code", "품번", 20),
    ("shape", "형태", 100),
    ("material", "재질", 100),
    ("printing", "인쇄", 100),
    ("coating", "코팅", 100),
    ("finishing", "후가공", 100),
)
MAX_IMAGES_PER_UPLOAD = 20


def _get(db, item_id: int) -> PortfolioItem:
    item = db.get(PortfolioItem, item_id)
    if item is None:
        raise HTTPException(404)
    return item


@router.get("/", response_class=HTMLResponse)
def showroom_list(
    request: Request, db: DbSession, user: AdminUser, box_type: str = "", industry: str = ""
):
    stmt = select(PortfolioItem)
    if box_type in BOX_TYPES:
        stmt = stmt.where(PortfolioItem.box_type == box_type)
    if industry in INDUSTRIES:
        stmt = stmt.where(PortfolioItem.industry == industry)
    items = db.scalars(
        stmt.order_by(PortfolioItem.sort_order.desc(), PortfolioItem.id.desc())
    ).all()
    return templates.TemplateResponse(
        request,
        "admin/showroom/list.html",
        {
            "title": "쇼룸 관리",
            "section": "showroom",
            "user": user,
            "items": items,
            "f": {"box_type": box_type, "industry": industry},
            "box_types": BOX_TYPES,
            "industries": INDUSTRIES,
        },
    )


def _render_form(request, user, item: PortfolioItem | None, v: dict, errors: dict, status=200):
    return templates.TemplateResponse(
        request,
        "admin/showroom/form.html",
        {
            "title": f"쇼룸 수정 — {item.name}" if item else "쇼룸 등록",
            "section": "showroom",
            "user": user,
            "item": item,
            "v": v,
            "errors": errors,
            "text_fields": TEXT_FIELDS,
            "box_types": BOX_TYPES,
            "industries": INDUSTRIES,
        },
        status_code=status,
    )


def _values(item: PortfolioItem) -> dict:
    v = {name: getattr(item, name) or "" for name, _, _ in TEXT_FIELDS}
    v |= {
        "box_type": item.box_type,
        "industry": item.industry,
        "description": item.description,
        "sort_order": str(item.sort_order),
        "is_published": item.is_published,
    }
    return v


def _clean(db, form: FormData, item: PortfolioItem | None) -> tuple[dict, dict]:
    v = {k: str(form.get(k, "")).strip() for k, _, _ in TEXT_FIELDS}
    v |= {k: str(form.get(k, "")).strip() for k in ("box_type", "industry", "description")}
    v["sort_order"] = str(form.get("sort_order", "0")).strip() or "0"
    v["is_published"] = bool(form.get("is_published"))
    errors = {}
    for name, label, max_len in TEXT_FIELDS:
        if len(v[name]) > max_len:
            errors[name] = f"{label}은(는) {max_len}자까지 입력할 수 있습니다."
    if not v["name"]:
        errors["name"] = "품명을 입력해 주세요."
    if v["box_type"] not in BOX_TYPES:
        errors["box_type"] = "박스형태를 골라 주세요."
    if v["industry"] not in INDUSTRIES:
        errors["industry"] = "업종을 골라 주세요."
    try:
        v["sort_order"] = int(v["sort_order"])
    except ValueError:
        errors["sort_order"] = "숫자로 입력해 주세요."
    if v["code"] and "code" not in errors:
        other = db.scalar(select(PortfolioItem).where(PortfolioItem.code == v["code"]))
        if other is not None and other is not item:
            errors["code"] = f"품번 {v['code']}는 이미 쓰고 있습니다."
    return v, errors


def _uploads(form: FormData, name: str) -> list[UploadFile]:
    return [u for u in form.getlist(name) if isinstance(u, UploadFile) and u.filename]


def _save(request: Request, db, user, item: PortfolioItem | None, form: FormData):
    v, errors = _clean(db, form, item)
    gallery = _uploads(form, "images")
    thumbs = _uploads(form, "thumb")
    if len(gallery) > MAX_IMAGES_PER_UPLOAD:
        errors["images"] = f"한 번에 {MAX_IMAGES_PER_UPLOAD}장까지 올릴 수 있습니다."
    if any((u.size or 0) > images.MAX_UPLOAD for u in gallery + thumbs):
        errors["images"] = "이미지는 한 장에 15MB까지 올릴 수 있습니다."
    if errors:
        return _render_form(request, user, item, v, errors, status=422)

    created: list[str] = []
    old_thumb = item.thumb_path if item else None
    try:
        new = item is None
        if new:
            item = PortfolioItem()
            db.add(item)
        for k in ("name", "box_type", "industry", "description", "sort_order", "is_published"):
            setattr(item, k, v[k])
        for k in ("shape", "material", "printing", "coating", "finishing"):
            setattr(item, k, v[k])
        item.code = v["code"] or None

        if thumbs:
            item.thumb_path = images.save_thumb(thumbs[0].file)
            created.append(item.thumb_path)
        elif form.get("remove_thumb"):
            item.thumb_path = None
        start = max((img.sort_order for img in item.images), default=-1) + 1
        for n, u in enumerate(gallery):
            rel, w, h = images.save_gallery(u.file)
            created.append(rel)
            item.images.append(PortfolioImage(path=rel, width=w, height=h, sort_order=start + n))
        db.commit()
    except images.ImageError as e:
        db.rollback()
        _cleanup(created)
        errors["images"] = str(e)
        return _render_form(request, user, None if new else item, v, errors, status=422)
    except Exception:
        db.rollback()
        _cleanup(created)
        raise

    if old_thumb and old_thumb != item.thumb_path:
        images.delete_if_unused(db, old_thumb)
    log.info("쇼룸 %s: %s (%s)", "등록" if new else "수정", item.name, user.email)
    return RedirectResponse(f"/admin/showroom/{item.id}?saved=1", status_code=303)


def _cleanup(paths: list[str]) -> None:
    from app.config import get_settings

    for rel in paths:
        (get_settings().media_public / rel).unlink(missing_ok=True)


@router.get("/new", response_class=HTMLResponse)
def new_form(request: Request, user: AdminUser):
    v = {"box_type": "", "industry": "", "sort_order": "0", "is_published": True}
    return _render_form(request, user, None, v, {})


@router.post("/new", response_class=HTMLResponse)
async def create(request: Request, db: DbSession, user: AdminUser):
    form = await request.form(max_files=MAX_IMAGES_PER_UPLOAD + 5)
    return _save(request, db, user, None, form)


@router.get("/{item_id:int}", response_class=HTMLResponse)
def edit_form(request: Request, db: DbSession, user: AdminUser, item_id: int):
    item = _get(db, item_id)
    return _render_form(request, user, item, _values(item), {})


@router.post("/{item_id:int}", response_class=HTMLResponse)
async def update(request: Request, db: DbSession, user: AdminUser, item_id: int):
    item = _get(db, item_id)
    form = await request.form(max_files=MAX_IMAGES_PER_UPLOAD + 5)
    return _save(request, db, user, item, form)


def _images(request, item: PortfolioItem):
    return templates.TemplateResponse(request, "admin/showroom/_images.html", {"item": item})


@router.post("/{item_id:int}/images/{image_id:int}/delete", response_class=HTMLResponse)
def delete_image(request: Request, db: DbSession, user: AdminUser, item_id: int, image_id: int):
    item = _get(db, item_id)
    img = next((i for i in item.images if i.id == image_id), None)
    if img is None:
        raise HTTPException(404)
    item.images.remove(img)
    db.commit()
    images.delete_if_unused(db, img.path)
    return _images(request, item)


@router.post("/{item_id:int}/images/{image_id:int}/move", response_class=HTMLResponse)
def move_image(
    request: Request, db: DbSession, user: AdminUser, item_id: int, image_id: int, dir: str = "up"
):
    item = _get(db, item_id)
    imgs = list(item.images)
    idx = next((n for n, i in enumerate(imgs) if i.id == image_id), None)
    if idx is None:
        raise HTTPException(404)
    to = idx - 1 if dir == "up" else idx + 1
    if 0 <= to < len(imgs):
        imgs[idx], imgs[to] = imgs[to], imgs[idx]
        for n, img in enumerate(imgs):
            img.sort_order = n
        db.commit()
        db.refresh(item, ["images"])
    return _images(request, item)


@router.post("/{item_id:int}/publish", response_class=HTMLResponse)
def toggle_publish(request: Request, db: DbSession, user: AdminUser, item_id: int):
    item = _get(db, item_id)
    item.is_published = not item.is_published
    db.commit()
    return templates.TemplateResponse(request, "admin/showroom/_publish.html", {"item": item})


@router.post("/{item_id:int}/delete")
def delete_item(request: Request, db: DbSession, user: AdminUser, item_id: int):
    item = _get(db, item_id)
    paths = [img.path for img in item.images] + [item.thumb_path]
    name = item.name
    db.delete(item)
    db.commit()
    for rel in paths:
        images.delete_if_unused(db, rel)
    log.warning("쇼룸 삭제: %s (%s)", name, user.email)
    url = "/admin/showroom/"
    if is_htmx(request):
        return Response(headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)
