"""공개 이미지(쇼룸) 업로드: WebP로 변환해 MEDIA_ROOT/public 아래에 저장합니다."""

import uuid
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import PortfolioImage, PortfolioItem

MAX_UPLOAD = 15 * 1024 * 1024
MAX_WIDTH = 1600  # 상세 갤러리
THUMB_SIZE = (800, 600)  # 목록 카드 4:3
FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


class ImageError(ValueError):
    pass


def _open(src: BinaryIO) -> Image.Image:
    try:
        im = Image.open(src)
        im.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise ImageError("이미지 파일을 읽을 수 없습니다.") from e
    if im.format not in FORMATS:
        raise ImageError("JPG, PNG, WebP, GIF 이미지만 올릴 수 있습니다.")
    im = ImageOps.exif_transpose(im)  # 휴대폰 사진 회전 보정
    return im.convert("RGBA") if im.mode in ("P", "LA", "RGBA") else im.convert("RGB")


def _save(im: Image.Image, folder: str) -> str:
    rel = f"{folder}/{uuid.uuid4().hex[:16]}.webp"
    dest = get_settings().media_public / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "WEBP", quality=82, method=6)
    return rel


def save_gallery(src: BinaryIO, folder: str = "portfolio") -> tuple[str, int, int]:
    im = _open(src)
    if im.width > MAX_WIDTH:
        im = im.resize((MAX_WIDTH, round(im.height * MAX_WIDTH / im.width)), Image.LANCZOS)
    return _save(im, folder), im.width, im.height


def save_thumb(src: BinaryIO, folder: str = "portfolio") -> str:
    """가운데를 기준으로 4:3으로 잘라 800×600으로 저장합니다."""
    im = ImageOps.fit(_open(src), THUMB_SIZE, Image.LANCZOS)
    return _save(im, folder)


def delete_if_unused(db: Session, rel: str | None) -> None:
    """다른 쇼룸 항목이 쓰지 않는 파일만 지웁니다. 커밋 후 호출합니다."""
    if not rel:
        return
    used = db.scalar(
        select(PortfolioImage.id).where(PortfolioImage.path == rel).limit(1)
    ) or db.scalar(select(PortfolioItem.id).where(PortfolioItem.thumb_path == rel).limit(1))
    if not used:
        (get_settings().media_public / rel).unlink(missing_ok=True)
