"""SQLAlchemy 모델. 새 모델 모듈은 여기서 import해야 Alembic autogenerate가 인식합니다."""

from app.models.base import Base, TimestampMixin
from app.models.inquiry import (
    Inquiry,
    InquiryFile,
    InquiryReply,
    InquiryReplyFile,
    InquirySpec,
)
from app.models.mold import Mold
from app.models.portfolio import PortfolioImage, PortfolioItem
from app.models.user import LoginAttempt, User

__all__ = [
    "Base",
    "Inquiry",
    "InquiryFile",
    "InquiryReply",
    "InquiryReplyFile",
    "InquirySpec",
    "LoginAttempt",
    "Mold",
    "PortfolioImage",
    "PortfolioItem",
    "TimestampMixin",
    "User",
]
