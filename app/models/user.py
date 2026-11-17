"""관리자 계정과 로그인 기록."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.content import ROLES
from app.models.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)  # 로그인 ID (소문자)
    name: Mapped[str] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(20), default="sales")  # ROLES 키
    password_hash: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 비밀번호 변경·비활성화 시 올려서 기존 세션을 모두 끊습니다.
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def role_label(self) -> str:
        return ROLES.get(self.role, self.role)


class LoginAttempt(Base):
    """로그인 시도. 최근 실패 횟수로 계정·IP별 잠금을 판단합니다 (기획서 7장 보안)."""

    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), index=True)
    ip: Mapped[str] = mapped_column(String(45), index=True)
    success: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
