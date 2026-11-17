"""쇼룸(제작 사례)."""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.content import BOX_TYPES, INDUSTRIES
from app.models.base import Base, TimestampMixin


class PortfolioItem(TimestampMixin, Base):
    __tablename__ = "portfolio_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(20), unique=True)  # 품번 (GP1001)
    name: Mapped[str] = mapped_column(String(100))  # 품명

    # 필터용 분류 (app.content.BOX_TYPES / INDUSTRIES 키)
    box_type: Mapped[str] = mapped_column(String(20), index=True)
    industry: Mapped[str] = mapped_column(String(20), index=True)

    # 사양 (원문 그대로 표시)
    shape: Mapped[str] = mapped_column(String(100), default="")  # 형태
    material: Mapped[str] = mapped_column(String(100), default="")  # 재질
    printing: Mapped[str] = mapped_column(String(100), default="")  # 인쇄
    coating: Mapped[str] = mapped_column(String(100), default="")  # 코팅
    finishing: Mapped[str] = mapped_column(String(100), default="")  # 후가공
    description: Mapped[str] = mapped_column(Text, default="")  # 박스설명

    # 목록 카드용 썸네일 (4:3). 없으면 첫 번째 갤러리 이미지를 씁니다.
    thumb_path: Mapped[str | None] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)  # 클수록 앞에 노출
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)

    # 기존 WordPress 글 ID: /?p=ID → /portfolio/{id} 301 연결에 사용
    wp_post_id: Mapped[int | None] = mapped_column(Integer, unique=True)

    images: Mapped[list[PortfolioImage]] = relationship(
        back_populates="item",
        order_by="PortfolioImage.sort_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def box_type_label(self) -> str:
        return BOX_TYPES.get(self.box_type, self.box_type)

    @property
    def industry_label(self) -> str:
        return INDUSTRIES.get(self.industry, self.industry)

    @property
    def thumb_url(self) -> str | None:
        if self.thumb_path:
            return f"/media/{self.thumb_path}"
        return self.images[0].url if self.images else None

    @property
    def specs(self) -> list[tuple[str, str]]:
        """상세 화면의 사양표 (값이 있는 항목만)."""
        rows = [
            ("품번", self.code or ""),
            ("형태", self.shape),
            ("재질", self.material),
            ("인쇄", self.printing),
            ("코팅", self.coating),
            ("후가공", self.finishing),
        ]
        return [(k, v) for k, v in rows if v]


class PortfolioImage(Base):
    __tablename__ = "portfolio_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio_items.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(255))  # media/public 기준 상대 경로
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    item: Mapped[PortfolioItem] = relationship(back_populates="images")

    @property
    def url(self) -> str:
        return f"/media/{self.path}"
