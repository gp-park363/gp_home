"""업로드 파일 저장. 견적 첨부는 비공개 폴더(MEDIA_ROOT/private)에 둡니다."""

import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path, PurePath
from typing import BinaryIO
from urllib.parse import quote

from fastapi.responses import FileResponse, Response

from app.config import get_settings


def safe_name(filename: str) -> str:
    """표시·다운로드용 원본 파일명 (경로·제어문자 제거)."""
    name = PurePath(filename.replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip() or "file"
    return name[-200:]


def save_private(src: BinaryIO, filename: str, folder: str) -> str:
    """원본 이름과 무관한 임의 이름으로 저장하고, media_private 기준 상대 경로를 돌려줍니다."""
    ext = PurePath(filename).suffix.lower()[:10]
    rel = f"{folder}/{datetime.now():%Y/%m}/{uuid.uuid4().hex}{ext}"
    dest = get_settings().media_private / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as out:
        shutil.copyfileobj(src, out, length=1024 * 1024)
    return rel


def private_path(rel: str) -> Path:
    return get_settings().media_private / rel


def delete_private(rel: str) -> None:
    private_path(rel).unlink(missing_ok=True)


def download_response(rel: str, filename: str, content_type: str = "") -> Response:
    """비공개 파일 내려받기. 권한 확인은 호출한 쪽에서 합니다.

    운영: Nginx가 X-Accel-Redirect로 직접 전송 (앱 워커를 붙잡지 않음)
    로컬·테스트: FileResponse
    """
    ctype = content_type or "application/octet-stream"
    if get_settings().is_prod:
        ascii_name = filename.encode("ascii", "replace").decode().replace('"', "")
        return Response(
            headers={
                "X-Accel-Redirect": f"/_private/{quote(rel)}",
                "Content-Type": ctype,
                "Content-Disposition": (
                    f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
                ),
                "Cache-Control": "private, no-store",
            }
        )
    path = private_path(rel)
    if not path.is_file():
        return Response("파일을 찾을 수 없습니다.", status_code=404)
    return FileResponse(
        path, media_type=ctype, filename=filename, headers={"Cache-Control": "private, no-store"}
    )
