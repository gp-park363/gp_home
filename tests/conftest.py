"""테스트 공통 설정.

- 개발 DB 이름 뒤에 _test를 붙인 별도 DB를 쓰고, 처음 한 번 마이그레이션합니다.
- 테스트마다 트랜잭션을 열고 끝나면 롤백하므로 데이터가 남지 않습니다.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

os.environ.setdefault("APP_ENV", "test")

# app을 import하기 전에 DATABASE_URL을 테스트 DB로 바꿔야 엔진이 테스트 DB를 가리킵니다.
from app.config import Settings  # noqa: E402

_dev_url = make_url(Settings().database_url)
TEST_DB_URL = _dev_url.set(database=f"{_dev_url.database}_test")
os.environ["DATABASE_URL"] = TEST_DB_URL.render_as_string(hide_password=False)

from fastapi.testclient import TestClient  # noqa: E402

from app.db import engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import PortfolioImage, PortfolioItem  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    admin = create_engine(_dev_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB_URL.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_URL.database}"'))
    admin.dispose()

    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
def db():
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield session
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        trans.rollback()
        conn.close()


@pytest.fixture
def client(db) -> TestClient:
    return TestClient(app)


@pytest.fixture
def make_portfolio(db):
    """쇼룸 항목 생성 도우미."""

    def _make(name="테스트 상자", box_type="lid", industry="food", images=1, **kw):
        item = PortfolioItem(name=name, box_type=box_type, industry=industry, **kw)
        for n in range(images):
            item.images.append(PortfolioImage(path=f"portfolio/t{n}.webp", width=800, height=600))
        db.add(item)
        db.flush()
        return item

    return _make


@pytest.fixture(autouse=True)
def _media_tmp(tmp_path, monkeypatch):
    """업로드 파일은 테스트마다 임시 폴더에 저장합니다."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "media_root", tmp_path / "media")
    return tmp_path / "media"


@pytest.fixture(autouse=True)
def outbox(db, monkeypatch) -> list:
    """SMTP 대신 보낸 메일을 모읍니다. 알림은 새 세션으로 조회하므로 테스트 세션을 쓰게 바꿉니다."""
    from contextlib import nullcontext

    from app.services import inquiry as inquiry_service
    from app.services import mailer

    sent: list = []
    monkeypatch.setattr(mailer, "deliver", lambda msg: sent.append(msg) or True)
    monkeypatch.setattr(inquiry_service, "_session", lambda: nullcontext(db))
    return sent


@pytest.fixture
def make_mold(db):
    from app.models import Mold

    def _make(box_type="lid", width=120, depth=80, height=40, **kw):
        mold = Mold(box_type=box_type, width=width, depth=depth, height=height, **kw)
        db.add(mold)
        db.flush()
        return mold

    return _make


@pytest.fixture
def make_user(db):
    from app.models import User
    from app.services import auth

    def _make(
        email="sales@goodpackage.test", name="김영업", role="sales", password="test-pass-123", **kw
    ):
        user = User(
            email=email, name=name, role=role, password_hash=auth.hash_password(password), **kw
        )
        db.add(user)
        db.flush()
        return user

    return _make


def login(client, email, password="test-pass-123"):
    return client.post(
        "/admin/login", data={"email": email, "password": password}, follow_redirects=False
    )


@pytest.fixture
def staff(client, make_user):
    """영업 계정으로 로그인한 클라이언트."""
    user = make_user()
    assert login(client, user.email).status_code == 303
    return user


@pytest.fixture
def admin(client, make_user):
    """관리자 계정으로 로그인한 클라이언트."""
    user = make_user(email="admin@goodpackage.test", name="이관리", role="admin")
    assert login(client, user.email).status_code == 303
    return user
