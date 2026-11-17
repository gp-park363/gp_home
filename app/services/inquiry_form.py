"""견적 폼 항목 정의와 서버 검증.

단계: 1 제작 사양 → 2 요청 내용·첨부 → 3 담당자 정보·동의 (기획서 4.1).
같은 정의로 필드 단위 검증(입력 직후), 단계 검증("다음" 버튼), 최종 검증(제출)을 합니다.
"""

import re
from dataclasses import dataclass
from pathlib import PurePath

from app import content

MAX_FILES = 5
MAX_FILE_SIZE = 9 * 1024 * 1024  # 개당 9MB (현 폼과 동일)
# 사진, 디자인·도면, 문서, 압축 파일
ALLOWED_EXTENSIONS = frozenset(
    {
        *("jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff", "heic"),
        *("pdf", "ai", "eps", "psd", "svg", "cdr", "dxf", "dwg"),
        *("hwp", "hwpx", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt"),
        *("zip", "7z"),
    }
)

STEPS = {1: "제작 사양", 2: "요청 내용", 3: "담당자 정보"}

PHONE_RE = re.compile(r"^0\d{1,2}\d{3,4}\d{4}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    step: int
    kind: str = "text"  # text, textarea, email, phone, mm, choice, box_type, mold, agree
    required: bool = False
    max_len: int = 100
    choices: tuple[str, ...] = ()


FIELDS: tuple[Field, ...] = (
    # 1. 제작 사양 — 모르면 비워 두고 요청 내용에 적도록 안내하므로 모두 선택 항목
    Field("box_type", "박스형태", 1, "box_type"),
    Field("width", "가로(장)", 1, "mm"),
    Field("depth", "세로(폭)", 1, "mm"),
    Field("height", "높이(고)", 1, "mm"),
    Field("mold_id", "추천 목형", 1, "mold"),
    Field("material", "종이재질", 1, "choice", choices=content.MATERIALS),
    Field("weight", "종이무게", 1, "weight"),
    Field("printing", "인쇄방식", 1, "choice", choices=content.PRINTINGS),
    Field("coating", "코팅방식", 1, "choice", choices=content.COATINGS),
    Field("foil", "박가공", 1, "choice", choices=content.FOILS),
    Field("emboss", "형압", 1, "choice", choices=content.EMBOSSES),
    Field("silk", "실크(에폭시)", 1, "choice", choices=content.SILKS),
    # 2. 요청 내용
    Field("title", "요청 제목", 2, required=True, max_len=200),
    Field("content", "요청 내용", 2, "textarea", max_len=5000),
    Field("quantity", "제작 수량", 2, max_len=50),
    Field("budget", "최대 예산", 2, max_len=50),
    # 3. 담당자 정보
    Field("company", "업체명", 3, required=True),
    Field("name", "담당자명", 3, required=True, max_len=50),
    Field("phone", "연락처", 3, "phone", required=True, max_len=20),
    Field("email", "이메일", 3, "email", required=True, max_len=200),
    Field("position", "담당자 직책", 3, required=True, max_len=50),
    Field("delivery_location", "납품 위치", 3, required=True, max_len=200),
    Field("agree", "개인정보 수집·이용 동의", 3, "agree", required=True),
)
FIELD_MAP = {f.name: f for f in FIELDS}
SPEC_FIELDS = (
    "box_type",
    "width",
    "depth",
    "height",
    "material",
    "weight",
    "printing",
    "coating",
    "foil",
    "emboss",
    "silk",
)


def _eul(word: str) -> str:
    """받침 유무에 따라 '을/를'을 붙입니다."""
    last = word.rstrip(")").split("(")[0][-1]
    has_final = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 > 0
    return f"{word}{'을' if has_final else '를'}"


def weights_for(material: str) -> tuple[str, ...]:
    return content.WEIGHTS_BY_MATERIAL.get(material, content.WEIGHTS)


def format_phone(digits: str) -> str:
    if digits.startswith("02"):
        return f"02-{digits[2:-4]}-{digits[-4:]}"
    return f"{digits[:3]}-{digits[3:-4]}-{digits[-4:]}"


def clean_field(f: Field, raw: str, data: dict[str, str]) -> tuple[object, str | None]:
    """(정리된 값, 오류 문구). 값이 비었고 필수가 아니면 ("", None)."""
    value = (raw or "").strip()
    if f.kind != "textarea":
        value = " ".join(value.split())
    if not value:
        if f.required:
            if f.kind == "agree":
                return False, "개인정보 수집·이용에 동의해 주세요."
            return "", f"{_eul(f.label)} 입력해 주세요."
        return (None if f.kind in ("mm", "mold", "box_type") else ""), None
    if len(value) > f.max_len:
        return value, f"{f.max_len}자 이내로 입력해 주세요."

    match f.kind:
        case "mm":
            num = value.replace(",", "").removesuffix("mm").strip()
            if not num.isdigit() or not 1 <= int(num) <= 3000:
                return value, "1~3000 사이의 숫자(mm)로 입력해 주세요."
            return int(num), None
        case "box_type":
            if value not in content.BOX_TYPES:
                return None, "박스형태를 다시 선택해 주세요."
        case "choice":
            if value not in f.choices:
                return value, f"{_eul(f.label)} 목록에서 선택해 주세요."
        case "weight":
            allowed = (*weights_for(data.get("material", "").strip()), content.WEIGHT_NONE)
            if value not in allowed:
                return value, "선택한 종이재질에 맞는 무게를 골라 주세요."
        case "mold":
            if not value.isdigit():
                return None, "추천 목형을 다시 선택해 주세요."
            return int(value), None  # 존재 여부는 DB가 필요해 라우터에서 확인
        case "phone":
            digits = re.sub(r"\D", "", value)
            if not PHONE_RE.match(digits):
                return value, "연락처를 숫자로 정확히 입력해 주세요. (예: 010-1234-5678)"
            return format_phone(digits), None
        case "email":
            if not EMAIL_RE.match(value):
                return value, "이메일 주소 형식을 확인해 주세요."
            return value.lower(), None
        case "agree":
            return True, None
    return value, None


def validate(data: dict[str, str], steps=(1, 2, 3)) -> tuple[dict[str, object], dict[str, str]]:
    clean, errors = {}, {}
    for f in FIELDS:
        if f.step not in steps:
            continue
        value, err = clean_field(f, data.get(f.name, ""), data)
        clean[f.name] = value
        if err:
            errors[f.name] = err
    return clean, errors


def check_file(filename: str, size: int) -> str | None:
    ext = PurePath(filename).suffix.lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        return f"{filename}: 올릴 수 없는 파일 형식입니다."
    if size > MAX_FILE_SIZE:
        return f"{filename}: 9MB를 넘습니다."
    if size == 0:
        return f"{filename}: 빈 파일입니다."
    return None


def first_error_step(errors: dict[str, str]) -> int:
    steps = [FIELD_MAP[n].step if n in FIELD_MAP else 3 for n in errors]
    if "files" in errors:
        steps.append(2)
    return min(steps) if steps else 1
