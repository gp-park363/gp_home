"""견적문의."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.content import BOX_TYPES, INQUIRY_STATUSES, REPLY_KINDS
from app.crypto import EncryptedString
from app.models.base import Base, TimestampMixin
from app.models.mold import Mold
from app.models.portfolio import PortfolioItem
from app.models.user import User


class Inquiry(TimestampMixin, Base):
    __tablename__ = "inquiries"
    __table_args__ = (Index("ix_inquiries_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)  # 접수번호 YYMMDD-NNN
    status: Mapped[str] = mapped_column(String(20), default="received", index=True)

    # 담당자 정보 — 연락처·이메일은 암호화 저장 (기획서 4.5)
    company: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(50))
    phone: Mapped[str] = mapped_column(EncryptedString)
    email: Mapped[str] = mapped_column(EncryptedString)
    position: Mapped[str] = mapped_column(String(50), default="")
    delivery_location: Mapped[str] = mapped_column(String(200), default="")

    # 요청 정보
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    quantity: Mapped[str] = mapped_column(String(50), default="")
    budget: Mapped[str] = mapped_column(String(50), default="")

    mold_id: Mapped[int | None] = mapped_column(ForeignKey("molds.id", ondelete="SET NULL"))
    portfolio_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_items.id", ondelete="SET NULL")
    )

    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    privacy_agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str] = mapped_column(String(45), default="")
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    # 기존 KBoard 글 ID: /?kboard_content_redirect=ID → /list/{id} 301 (이관 단계)
    wp_post_id: Mapped[int | None] = mapped_column(Integer, unique=True)

    spec: Mapped[InquirySpec | None] = relationship(
        back_populates="inquiry", cascade="all, delete-orphan", lazy="selectin"
    )
    files: Mapped[list[InquiryFile]] = relationship(
        back_populates="inquiry",
        cascade="all, delete-orphan",
        order_by="InquiryFile.id",
        lazy="selectin",
    )
    replies: Mapped[list[InquiryReply]] = relationship(
        back_populates="inquiry", cascade="all, delete-orphan", order_by="InquiryReply.id"
    )
    mold: Mapped[Mold | None] = relationship()
    portfolio_item: Mapped[PortfolioItem | None] = relationship()
    assignee: Mapped[User | None] = relationship()

    @property
    def status_label(self) -> str:
        return INQUIRY_STATUSES.get(self.status, self.status)


class InquirySpec(Base):
    __tablename__ = "inquiry_specs"

    id: Mapped[int] = mapped_column(primary_key=True)
    inquiry_id: Mapped[int] = mapped_column(
        ForeignKey("inquiries.id", ondelete="CASCADE"), unique=True
    )
    box_type: Mapped[str | None] = mapped_column(String(20))
    width: Mapped[int | None] = mapped_column(Integer)  # 가로(장) mm
    depth: Mapped[int | None] = mapped_column(Integer)  # 세로(폭) mm
    height: Mapped[int | None] = mapped_column(Integer)  # 높이(고) mm
    material: Mapped[str] = mapped_column(String(30), default="")
    weight: Mapped[str] = mapped_column(String(20), default="")  # 평량
    printing: Mapped[str] = mapped_column(String(30), default="")
    coating: Mapped[str] = mapped_column(String(30), default="")
    foil: Mapped[str] = mapped_column(String(30), default="")  # 박
    emboss: Mapped[str] = mapped_column(String(30), default="")  # 형압
    silk: Mapped[str] = mapped_column(String(30), default="")  # 실크(에폭시)

    inquiry: Mapped[Inquiry] = relationship(back_populates="spec")

    @property
    def box_type_label(self) -> str:
        return BOX_TYPES.get(self.box_type or "", "")

    @property
    def size_label(self) -> str:
        dims = [self.width, self.depth, self.height]
        return "×".join(str(d) if d else "-" for d in dims) if any(dims) else ""

    @property
    def rows(self) -> list[tuple[str, str]]:
        """값이 있는 사양만 (라벨, 값)으로."""
        pairs = [
            ("박스형태", self.box_type_label),
            ("사이즈(mm)", self.size_label),
            ("종이재질", " ".join(v for v in (self.material, self.weight) if v)),
            ("인쇄방식", self.printing),
            ("코팅방식", self.coating),
            ("박가공", self.foil),
            ("형압", self.emboss),
            ("실크", self.silk),
        ]
        return [(k, v) for k, v in pairs if v]


class InquiryFile(Base):
    """견적 첨부. MEDIA_ROOT/private 아래에 두고 권한 확인 후 X-Accel-Redirect로 내려 줍니다."""

    __tablename__ = "inquiry_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    inquiry_id: Mapped[int] = mapped_column(
        ForeignKey("inquiries.id", ondelete="CASCADE"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(255))  # media_private 기준 상대 경로
    size: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    inquiry: Mapped[Inquiry] = relationship(back_populates="files")


class InquiryReply(Base):
    """견적 처리 이력: 고객 답변(메일 발송), 내부 메모, 상태·담당 변경 기록."""

    __tablename__ = "inquiry_replies"

    id: Mapped[int] = mapped_column(primary_key=True)
    inquiry_id: Mapped[int] = mapped_column(
        ForeignKey("inquiries.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(10))  # REPLY_KINDS 키
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # 작성자 이름 (계정이 지워지거나 이관 데이터여도 남도록 따로 보관)
    author_name: Mapped[str] = mapped_column(String(50), default="")
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 기존 KBoard 댓글 ID (이관 단계)
    wp_comment_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    inquiry: Mapped[Inquiry] = relationship(back_populates="replies")
    files: Mapped[list[InquiryReplyFile]] = relationship(
        back_populates="reply",
        cascade="all, delete-orphan",
        order_by="InquiryReplyFile.id",
        lazy="selectin",
    )

    @property
    def kind_label(self) -> str:
        return REPLY_KINDS.get(self.kind, self.kind)


class InquiryReplyFile(Base):
    """답변 첨부(견적서 등). 메일에 첨부하고 비공개 폴더에 보관합니다."""

    __tablename__ = "inquiry_reply_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    reply_id: Mapped[int] = mapped_column(
        ForeignKey("inquiry_replies.id", ondelete="CASCADE"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(100), default="")

    reply: Mapped[InquiryReply] = relationship(back_populates="files")
