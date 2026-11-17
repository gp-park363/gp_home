"""입력한 규격과 비슷한 기존 목형 찾기.

세 치수가 모두 허용 오차 안에 드는 목형을, 치수 차이 합이 작은 순으로 돌려줍니다.
기존 목형을 쓰면 목형 제작비가 들지 않아 고객 예산을 줄일 수 있습니다.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Mold

# 치수별 허용 오차: max(TOL_MM, 입력값 × TOL_RATIO). 영업 담당과 맞춰 조정합니다.
TOL_MM = 10
TOL_RATIO = 0.10
LIMIT = 5


@dataclass(frozen=True)
class Match:
    mold: Mold
    diffs: tuple[int, int, int]  # 목형 - 입력 (mm)

    @property
    def exact(self) -> bool:
        return self.diffs == (0, 0, 0)


def tolerance(value: int) -> int:
    return max(TOL_MM, round(value * TOL_RATIO))


def find_similar(
    db: Session, box_type: str | None, width: int, depth: int, height: int, limit: int = LIMIT
) -> list[Match]:
    dw, dd, dh = (
        func.abs(Mold.width - width),
        func.abs(Mold.depth - depth),
        func.abs(Mold.height - height),
    )
    q = (
        select(Mold)
        .where(
            Mold.is_active,
            dw <= tolerance(width),
            dd <= tolerance(depth),
            dh <= tolerance(height),
        )
        .order_by(dw + dd + dh, Mold.id)
        .limit(limit)
    )
    if box_type:
        q = q.where(Mold.box_type == box_type)
    return [Match(m, (m.width - width, m.depth - depth, m.height - height)) for m in db.scalars(q)]
