"""개인정보(연락처·이메일) 컬럼 암호화.

Fernet(AES-128-CBC + HMAC)으로 저장하므로 DB 덤프만으로는 읽을 수 없습니다.
암호문은 매번 달라 DB에서 값으로 검색할 수 없습니다 — 조회는 다른 키(접수번호 등)로 합니다.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.config import get_settings


@lru_cache
def _fernet() -> MultiFernet:
    keys = [k.strip() for k in get_settings().data_keys.split(",") if k.strip()]
    return MultiFernet([Fernet(k) for k in keys])


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


class EncryptedString(TypeDecorator):
    """파이썬에서는 평문 str, DB에는 Fernet 토큰(text)으로 저장됩니다."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt(value)

    def process_result_value(self, value, dialect):
        return None if value is None else decrypt(value)
