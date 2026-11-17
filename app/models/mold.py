"""보유 목형. 견적 폼에서 입력한 규격과 비슷한 목형을 추천하는 데 씁니다."""

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.content import BOX_TYPES
from app.models.base import Base, TimestampMixin


class Mold(TimestampMixin, Base):
    __tablename__ = "molds"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(30), unique=True)  # 사내 목형번호
    box_type: Mapped[str] = mapped_column(String(20), index=True)  # BOX_TYPES 키
    # 내치수(mm): 가로(장) × 세로(폭) × 높이(고)
    width: Mapped[int] = mapped_column(Integer)
    depth: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    memo: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def box_type_label(self) -> str:
        return BOX_TYPES.get(self.box_type, self.box_type)

    @property
    def size_label(self) -> str:
        return f"{self.width}×{self.depth}×{self.height}"
