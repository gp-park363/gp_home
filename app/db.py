from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI 의존성: 요청마다 세션을 열고 닫습니다."""
    with SessionLocal() as session:
        yield session


# 라우터에서 `db: DbSession`으로 사용
DbSession = Annotated[Session, Depends(get_db)]
