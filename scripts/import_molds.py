"""목형 목록(엑셀 .xlsx 또는 CSV)을 molds 테이블로 가져옵니다 (목형번호 기준 덮어쓰기).

    python -m scripts.import_molds 파일.xlsx
    make import-molds f=scripts/data/sample_molds.csv     # 개발용 샘플

관리자 화면(목형 → 일괄 등록)과 같은 규칙입니다. 열 이름은 app/services/mold_import.py 참고.
"""

import argparse
from pathlib import Path

from app.db import SessionLocal
from app.services import mold_import


def run(path: str) -> None:
    p = Path(path)
    rows = mold_import.read_rows(p.name, p.read_bytes())
    with SessionLocal() as db:
        res = mold_import.apply(db, rows)
        if res.errors:
            print("\n".join(res.errors))
            raise SystemExit(f"오류 {len(res.errors)}건 — 아무것도 저장하지 않았습니다.")
        db.commit()
    print(f"목형 추가 {res.added}건, 갱신 {res.updated}건")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file")
    try:
        run(ap.parse_args().file)
    except ValueError as e:
        raise SystemExit(str(e)) from None


if __name__ == "__main__":
    main()
