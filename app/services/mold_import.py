"""목형 일괄 등록·내보내기 (엑셀 .xlsx 또는 CSV).

열 이름은 한글(목형번호, 박스형태, 가로, 세로, 높이, 메모, 사용) 또는
영문(code, box_type, width, depth, height, memo, active) 모두 받습니다.
- 박스형태는 키(lid) 또는 표시 이름(맞뚜껑형).
- 목형번호가 같은 행은 덮어씁니다. 목형번호가 없으면 새로 추가합니다.
- 오류가 한 줄이라도 있으면 아무것도 저장하지 않습니다.
"""

import csv
import io
from dataclasses import dataclass, field

from openpyxl import Workbook, load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content import BOX_TYPES
from app.models import Mold

COLUMNS = (  # (영문 키, 한글 열 이름)
    ("code", "목형번호"),
    ("box_type", "박스형태"),
    ("width", "가로"),
    ("depth", "세로"),
    ("height", "높이"),
    ("memo", "메모"),
    ("active", "사용"),
)
HEADER_ALIASES = {ko: en for en, ko in COLUMNS} | {en: en for en, _ in COLUMNS}
BY_LABEL = {label: key for key, label in BOX_TYPES.items()}
MAX_ROWS = 5000
FALSE_WORDS = {"n", "no", "x", "false", "0", "아니오", "미사용", "사용안함"}


@dataclass
class Result:
    added: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def parse_row(row: dict) -> dict:
    raw_type = _text(row.get("box_type"))
    box_type = raw_type if raw_type in BOX_TYPES else BY_LABEL.get(raw_type)
    if not box_type:
        raise ValueError(f"박스형태를 알 수 없습니다: {raw_type or '(빈칸)'}")
    dims = {}
    for key, label in (("width", "가로"), ("depth", "세로"), ("height", "높이")):
        raw = _text(row.get(key)).replace(",", "").removesuffix("mm").strip()
        try:
            dims[key] = int(float(raw))
        except ValueError:
            raise ValueError(f"{label} 값이 숫자가 아닙니다: {raw or '(빈칸)'}") from None
        if not 0 < dims[key] <= 3000:
            raise ValueError(f"{label} 값은 1~3000mm여야 합니다: {dims[key]}")
    code = _text(row.get("code"))[:30] or None
    return {
        "code": code,
        "box_type": box_type,
        **dims,
        "memo": _text(row.get("memo")),
        "is_active": _text(row.get("active")).lower() not in FALSE_WORDS,
    }


def read_rows(filename: str, data: bytes) -> list[dict]:
    """파일에서 (열 이름 → 값) 행 목록을 읽습니다. 형식이 맞지 않으면 ValueError."""
    if filename.lower().endswith(".xlsx"):
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as e:
            raise ValueError("엑셀 파일을 읽을 수 없습니다.") from e
        values = list(wb.worksheets[0].iter_rows(values_only=True))
    elif filename.lower().endswith(".csv"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp949", errors="replace")  # 엑셀 기본 CSV(ANSI)
        values = list(csv.reader(io.StringIO(text)))
    else:
        raise ValueError("엑셀(.xlsx) 또는 CSV 파일만 올릴 수 있습니다.")

    if not values:
        raise ValueError("빈 파일입니다.")
    header = [HEADER_ALIASES.get(_text(h)) for h in values[0]]
    missing = [ko for en, ko in COLUMNS[1:5] if en not in header]
    if missing:
        raise ValueError(f"첫 줄에 열 이름이 필요합니다: {', '.join(missing)}")
    rows = [
        {k: v for k, v in zip(header, r, strict=False) if k}
        for r in values[1:]
        if any(_text(v) for v in r)
    ]
    if len(rows) > MAX_ROWS:
        raise ValueError(f"한 번에 {MAX_ROWS}행까지 올릴 수 있습니다.")
    return rows


def apply(db: Session, rows: list[dict]) -> Result:
    """검증 후 저장(flush). 오류가 있으면 아무것도 바꾸지 않습니다. 커밋은 호출한 쪽에서."""
    res = Result()
    parsed: list[dict] = []
    seen: dict[str, int] = {}
    for n, row in enumerate(rows, start=2):
        try:
            data = parse_row(row)
        except ValueError as e:
            res.errors.append(f"{n}행: {e}")
            continue
        if data["code"]:
            if data["code"] in seen:
                first = seen[data["code"]]
                res.errors.append(f"{n}행: 목형번호 {data['code']}가 {first}행과 겹칩니다")
                continue
            seen[data["code"]] = n
        parsed.append(data)
    if res.errors:
        return res

    existing = {
        m.code: m for m in db.scalars(select(Mold).where(Mold.code.in_(list(seen)))) if m.code
    }
    for data in parsed:
        mold = existing.get(data["code"]) if data["code"] else None
        if mold is None:
            db.add(Mold(**data))
            res.added += 1
        else:
            for k, v in data.items():
                setattr(mold, k, v)
            res.updated += 1
    db.flush()
    return res


def export_xlsx(molds: list[Mold]) -> bytes:
    """목록 내려받기. 같은 양식으로 고쳐서 다시 올릴 수 있습니다."""
    wb = Workbook()
    ws = wb.active
    ws.title = "목형"
    ws.append([ko for _, ko in COLUMNS])
    for m in molds:
        ws.append(
            [
                m.code or "",
                m.box_type_label,
                m.width,
                m.depth,
                m.height,
                m.memo,
                "Y" if m.is_active else "N",
            ]
        )
    for col, width in zip("ABCDEFG", (14, 12, 8, 8, 8, 40, 6), strict=True):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
